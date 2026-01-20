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
logger = logging.getLogger(__name__)



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
        webhook_data = request.data or {}
        logger.info("PayG Webhook received: %s", webhook_data)

        webhook_log = PaymentWebhookLog.objects.create(
            webhook_data=webhook_data,
            processed=False,
        )

        try:
            # 🔐 Auth validation (DO NOT FAIL HARD)
            auth_key = (
                webhook_data.get("auth_key")
                or request.headers.get("X-PayG-AuthKey")
            )

            if auth_key != settings.PAYG_CONFIG["AUTHENTICATION_KEY"]:
                logger.warning("AuthKey mismatch, continuing for safety")

            # 🔑 PayG OrderKeyId (MAIN KEY)
            payg_order_id = webhook_data.get("OrderKeyId")
            if not payg_order_id:
                logger.error("OrderKeyId missing in webhook")
                return Response({"success": True}, status=200)

            payment = Payment.objects.filter(
                payg_order_id=payg_order_id
            ).first()

            if not payment:
                logger.error("Payment not found for OrderKeyId: %s", payg_order_id)
                return Response({"success": True}, status=200)

            # 🟡 SAFE STATUS HANDLING
            raw_status = (
                webhook_data.get("TxnStatus")
                or webhook_data.get("PaymentStatus")
                or webhook_data.get("status")
                or ""
            )

            raw_status = str(raw_status).upper()  # 🔥 FIX

            status_mapping = {
                "1": "SUCCESS",
                "SUCCESS": "SUCCESS",
                "APPROVED": "SUCCESS",
                "COMPLETED": "SUCCESS",
                "0": "FAILED",
                "FAILED": "FAILED",
                "FAILURE": "FAILED",
                "PENDING": "PENDING",
            }

            new_status = status_mapping.get(raw_status, "PENDING")

            # 🔄 Update payment
            payment.status = new_status
            payment.transaction_id = webhook_data.get("TransactionId")
            payment.payment_method = webhook_data.get("PaymentType")
            payment.webhook_response = webhook_data

            if new_status == "SUCCESS" and not payment.payment_completed_at:
                payment.payment_completed_at = timezone.now()

            payment.save()

            webhook_log.payment = payment
            webhook_log.processed = True
            webhook_log.save()

            logger.info("Payment %s updated to %s", payment.order_id, new_status)

            return Response({"success": True}, status=200)

        except Exception:
            logger.exception("Webhook processing failed")
            return Response({"success": True}, status=200)



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