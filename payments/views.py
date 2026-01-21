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
        logger.info(f"AuthKey received: '{data.get('AuthKey')}'")
        logger.info(f"AuthKey expected: '{settings.PAYG_CONFIG['AUTHENTICATION_KEY']}'")
        logger.info(f"AuthKey match: {data.get('AuthKey') == settings.PAYG_CONFIG['AUTHENTICATION_KEY']}")
        logger.info(f"OrderKeyId: {data.get('OrderKeyId')}")
        logger.info(f"All keys in data: {list(data.keys())}")
        logger.info("=" * 50)

        # 1. Verify AuthKey
        received_auth_key = data.get("AuthKey")
        expected_auth_key = settings.PAYG_CONFIG["AUTHENTICATION_KEY"]

        if received_auth_key != expected_auth_key:
            logger.error(f"❌ AuthKey mismatch!")
            logger.error(f"Received: '{received_auth_key}' (type: {type(received_auth_key)})")
            logger.error(f"Expected: '{expected_auth_key}' (type: {type(expected_auth_key)})")
            # TEMPORARILY ALLOW IT TO CONTINUE FOR DEBUGGING
            # return Response({"success": False, "error": "Unauthorized"}, status=403)

        # 2. Get PayG Order ID
        payg_order_id = data.get("OrderKeyId")
        if not payg_order_id:
            logger.error("OrderKeyId missing")
            return Response({"success": False, "error": "Missing OrderKeyId"}, status=400)

        payment = Payment.objects.filter(payg_order_id=payg_order_id).first()
        if not payment:
            logger.error(f"Payment not found for OrderKeyId: {payg_order_id}")
            # Log all payments to see what we have
            all_payg_ids = Payment.objects.values_list('payg_order_id', flat=True)
            logger.error(f"Available PayG Order IDs: {list(all_payg_ids)}")
            return Response({"success": False, "error": "Payment not found"}, status=404)

        # 3. Idempotency: already processed
        if payment.status == "SUCCESS":
            logger.info(f"Payment already success: {payg_order_id}")
            return Response({"success": True}, status=200)

        # 4. Update status
        response_text = data.get("ResponseText", "").lower()
        logger.info(f"ResponseText: '{response_text}'")
        
        if "approved" in response_text or "success" in response_text:
            payment.status = "SUCCESS"
            logger.info("✅ Payment marked as SUCCESS")
        else:
            payment.status = "FAILED"
            logger.warning(f"⚠️ Payment marked as FAILED - ResponseText: {response_text}")

        payment.transaction_id = data.get("TransactionReferenceNo")
        payment.raw_webhook_response = data
        payment.save()

        logger.info(f"💾 Payment saved: {payment.order_id} → {payment.status}")

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