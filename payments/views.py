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
import logging
logger = logging.getLogger("payments    ")



class InitiatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        amount = serializer.validated_data["amount"]

        # 🔑 Internal order ID (YOUR system)
        order_id = f"YK{uuid.uuid4().hex[:12].upper()}"

        # 1️⃣ Create pending payment FIRST
        payment = Payment.objects.create(
            user=user,
            order_id=order_id,
            amount=amount,
            customer_name=user.full_name,
            customer_email=user.email,
            customer_phone=user.phone or "9999999999",
            status="PENDING",
        )

        payment_gateway = PayGPaymentGateway()

        payment_data = {
            "order_id": order_id,
            "amount": float(amount),
            "customer_name": user.full_name,
            "customer_email": user.email,
            "customer_phone": user.phone or "9999999999",
            "user_id": str(user.id),
            "callback_url": settings.PAYG_CONFIG["CALLBACK_URL"],
            "return_url": settings.PAYG_CONFIG["RETURN_URL"],
        }

        result = payment_gateway.create_payment_request(payment_data)

        # ❌ Payment gateway failure
        if not result.get("success"):
            payment.status = "FAILED"
            payment.payment_gateway_response = result
            payment.save()

            return Response(
                {
                    "success": False,
                    "message": "Payment initiation failed",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 🔴 VERY IMPORTANT PART 🔴
        payg_data = result.get("data", {})
        payg_order_id = payg_data.get("OrderKeyId")

        if not payg_order_id:
            payment.status = "FAILED"
            payment.payment_gateway_response = result
            payment.save()

            return Response(
                {
                    "success": False,
                    "message": "Invalid PayG response (OrderKeyId missing)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ✅ SAVE PayG OrderKeyId (WEBHOOK KEY)
        payment.payg_order_id = payg_order_id
        payment.payment_gateway_response = payg_data
        payment.save()

        return Response(
            {
                "success": True,
                "order_id": order_id,
                "payment_url": payg_data.get("PaymentProcessUrl"),
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        data = request.data
        
        # 🔍 LOG EVERYTHING FOR DEBUGGING
        logger.info("=" * 50)
        logger.info("WEBHOOK RECEIVED - FULL DATA:")
        logger.info(f"Data: {data}")
        logger.info("=" * 50)

        # 1. Create webhook log entry FIRST (even if processing fails)
        webhook_log = PaymentWebhookLog.objects.create(
            webhook_data=data,
            processed=False
        )
        logger.info(f"📝 Webhook log created: ID {webhook_log.id}")

        try:
            # 2. Get PayG Order ID
            payg_order_id = data.get("OrderKeyId")
            if not payg_order_id:
                logger.error("❌ OrderKeyId missing in webhook")
                webhook_log.processed = False
                webhook_log.save()
                return Response({"success": False, "error": "Missing OrderKeyId"}, status=400)

            # 3. Find payment by PayG Order ID
            payment = Payment.objects.filter(payg_order_id=payg_order_id).first()
            if not payment:
                logger.error(f"❌ Payment not found for OrderKeyId: {payg_order_id}")
                webhook_log.processed = False
                webhook_log.save()
                return Response({"success": False, "error": "Payment not found"}, status=404)

            # Link webhook log to payment
            webhook_log.payment = payment
            webhook_log.save()
            logger.info(f"🔗 Webhook log linked to payment: {payment.order_id}")

            # 4. Idempotency: already processed
            if payment.status == "SUCCESS":
                logger.info(f"✅ Payment already processed: {payg_order_id}")
                webhook_log.processed = True
                webhook_log.save()
                return Response({"success": True, "message": "Already processed"}, status=200)

            # 5. Extract payment details from PayG webhook
            payment_status = data.get("PaymentStatus")
            payment_response_text = data.get("PaymentResponseText", "").lower()
            order_payment_status_text = data.get("OrderPaymentStatusText", "").lower()
            
            logger.info(f"Payment Status Code: {payment_status}")
            logger.info(f"Payment Response Text: {payment_response_text}")
            logger.info(f"Order Payment Status Text: {order_payment_status_text}")

            # 6. Determine if payment is successful
            is_success = (
                payment_status == 1 or 
                "approved" in payment_response_text or 
                "paid" in order_payment_status_text or
                "success" in payment_response_text
            )

            if is_success:
                payment.status = "SUCCESS"
                payment.payment_completed_at = timezone.now()
                logger.info(f"✅ Payment marked as SUCCESS: {payment.order_id}")
            else:
                payment.status = "FAILED"
                logger.warning(f"⚠️ Payment marked as FAILED: {payment.order_id}")

            # 7. Map PayG payment method to your choices
            payg_payment_method = data.get("PaymentMethod", "").upper()
            payment_method_mapping = {
                "UPI": "UPI",
                "DEBIT CARD": "DEBIT_CARD",
                "CREDIT CARD": "CREDIT_CARD",
                "DEBITCARD": "DEBIT_CARD",
                "CREDITCARD": "CREDIT_CARD",
                "NET BANKING": "NET_BANKING",
                "NETBANKING": "NET_BANKING",
                "WALLET": "WALLET",
            }
            payment.payment_method = payment_method_mapping.get(
                payg_payment_method, 
                "UPI"  # Default fallback
            )

            # 8. Save transaction details
            payment.transaction_id = (
                data.get("PaymentTransactionId") or 
                data.get("PaymentTransactionRefNo") or
                data.get("TransactionId")
            )
            
            # Save the full webhook response
            payment.webhook_response = data
            
            # Save the payment
            payment.save()

            # Mark webhook as processed
            webhook_log.processed = True
            webhook_log.save()

            logger.info(f"💾 Payment updated successfully:")
            logger.info(f"   Order ID: {payment.order_id}")
            logger.info(f"   Status: {payment.status}")
            logger.info(f"   Transaction ID: {payment.transaction_id}")
            logger.info(f"   Payment Method: {payment.payment_method}")
            logger.info(f"   Amount: {payment.amount}")

            return Response({
                "success": True, 
                "message": "Payment updated successfully",
                "order_id": payment.order_id,
                "status": payment.status
            }, status=200)

        except Exception as e:
            logger.error(f"❌ Exception in webhook processing: {str(e)}")
            logger.exception(e)
            webhook_log.processed = False
            webhook_log.save()
            return Response({
                "success": False, 
                "error": "Internal server error"
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