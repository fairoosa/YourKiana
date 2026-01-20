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
import looger
logger = logging.getLogger(__name__)


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
        webhook_data = request.data
        logger.info("Webhook received: %s", webhook_data)

        webhook_log = PaymentWebhookLog.objects.create(
            webhook_data=webhook_data,
            processed=False
        )

        try:
            order_id = webhook_data.get('order_id')
            payg_order_id = webhook_data.get('OrderKeyId')
            transaction_id = webhook_data.get('TransactionId')
            payment_method = webhook_data.get('PaymentMethod')
            payment_status = webhook_data.get('status', '').upper()

            payment = None
            if order_id:
                payment = Payment.objects.filter(order_id=order_id).first()
            if not payment and payg_order_id:
                payment = Payment.objects.filter(payg_order_id=payg_order_id).first()

            if not payment:
                return Response({'success': False, 'error': 'Payment not found'}, status=404)

            if payment_status in ['SUCCESS', 'SUCCESSFUL', 'COMPLETED', 'TXN_SUCCESS']:
                payment.status = 'SUCCESS'
                payment.payment_completed_at = timezone.now()
            elif payment_status in ['FAILED', 'FAILURE', 'TXN_FAILED']:
                payment.status = 'FAILED'
            else:
                payment.status = 'PENDING'

            payment.transaction_id = transaction_id
            payment.payment_method = payment_method
            payment.webhook_response = webhook_data
            payment.save()

            webhook_log.payment = payment
            webhook_log.processed = True
            webhook_log.save()

            return Response({'success': True}, status=200)

        except Exception as e:
            logger.exception(e)
            return Response({'success': False, 'error': str(e)}, status=500)





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