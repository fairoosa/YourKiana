from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import uuid

from .models import Payment, PaymentWebhookLog
from .serializers import (
    PaymentInitiateSerializer,
    PaymentSerializer,
    PaymentStatusSerializer
)
from .utils import PayGPaymentGateway



class InitiatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_id = f"YK{uuid.uuid4().hex[:12].upper()}"
        user = request.user

        payment = Payment.objects.create(
            user=user,
            order_id=order_id,
            amount=serializer.validated_data['amount'],
            customer_name=user.full_name,
            customer_email=user.email,
            customer_phone=user.phone or '9999999999',
            status='PENDING'
        )

        payment_gateway = PayGPaymentGateway()

        payment_data = {
            'order_id': order_id,
            'amount': float(serializer.validated_data['amount']),
            'customer_name': user.full_name,
            'customer_email': user.email,
            'customer_phone': user.phone or '9999999999',
            'user_id': str(user.id),
            'callback_url': settings.PAYG_CONFIG['CALLBACK_URL'],
            'return_url': settings.PAYG_CONFIG['RETURN_URL'],
        }

        result = payment_gateway.create_payment_request(payment_data)

        if not result['success']:
            payment.status = 'FAILED'
            payment.payment_gateway_response = result
            payment.save()

            return Response({
                'success': False,
                'message': 'Payment initiation failed'
            }, status=status.HTTP_400_BAD_REQUEST)

        # ✅ SUCCESS
        payment.payg_order_id = result['data']['OrderKeyId']
        payment.payment_gateway_response = result['data']
        payment.save()

        return Response({
            'success': True,
            'order_id': order_id,
            'payment_url': result['data']['PaymentProcessUrl']
        }, status=status.HTTP_200_OK)



@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Handle PayG payment webhook.
        """
        webhook_data = request.data

        # Log the webhook
        webhook_log = PaymentWebhookLog.objects.create(
            webhook_data=webhook_data,
            processed=False
        )

        try:
            # Extract webhook fields
            order_id = webhook_data.get('order_id') or webhook_data.get('OrderKeyId')
            transaction_id = webhook_data.get('transaction_id') or webhook_data.get('TransactionId')
            payment_status = webhook_data.get('status', '').upper()
            payment_method = webhook_data.get('payment_method') or webhook_data.get('PaymentMethod')
            auth_key = request.headers.get('X-PayG-AuthKey') or webhook_data.get('auth_key')

            # Validate Order PostBack AuthKey
            if auth_key != "okjhn78312f8uyt148b304c55723iuyt":
                return Response({
                    'success': False,
                    'error': 'Invalid AuthKey'
                }, status=400)

            if not order_id:
                return Response({
                    'success': False,
                    'error': 'Order ID missing'
                }, status=400)

            # Fetch payment
            try:
                payment = Payment.objects.get(order_id=order_id)
                webhook_log.payment = payment
                webhook_log.save()
            except Payment.DoesNotExist:
                return Response({
                    'success': False,
                    'error': 'Payment not found'
                }, status=404)

            # Map PayG status to your DB status
            status_mapping = {
                'SUCCESS': 'SUCCESS',
                'COMPLETED': 'SUCCESS',
                'FAILED': 'FAILED',
                'PENDING': 'PENDING',
            }
            new_status = status_mapping.get(payment_status, 'PENDING')

            # Update payment
            payment.status = new_status
            payment.transaction_id = transaction_id
            payment.payment_method = payment_method
            payment.webhook_response = webhook_data
            if new_status == 'SUCCESS':
                payment.payment_completed_at = timezone.now()
            payment.save()

            # Mark webhook as processed
            webhook_log.processed = True
            webhook_log.save()

            return Response({
                'success': True,
                'message': 'Webhook processed successfully'
            }, status=200)

        except Exception as e:
            return Response({
                'success': False,
                'error': f'Webhook processing error: {str(e)}'
            }, status=500)




class PaymentStatusView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, order_id):
        try:
            payment = Payment.objects.get(
                order_id=order_id,
                user=request.user
            )
            
            serializer = PaymentSerializer(payment)
            return Response({
                'success': True,
                'payment': serializer.data
            }, status=status.HTTP_200_OK)
            
        except Payment.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Payment not found'
            }, status=status.HTTP_404_NOT_FOUND)

class PaymentHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer
    
    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)

class PaymentVerifyView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Manually verify payment status with PayG"""
        order_id = request.data.get('order_id')
        
        if not order_id:
            return Response({
                'success': False,
                'error': 'Order ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            payment = Payment.objects.get(
                order_id=order_id,
                user=request.user
            )
            
            # TODO: Call PayG API to verify payment status
            # This depends on PayG's API documentation
            
            return Response({
                'success': True,
                'payment': PaymentSerializer(payment).data
            }, status=status.HTTP_200_OK)
            
        except Payment.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Payment not found'
            }, status=status.HTTP_404_NOT_FOUND)