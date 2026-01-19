from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()



class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('UPI', 'UPI'),
        ('DEBIT_CARD', 'Debit Card'),
        ('CREDIT_CARD', 'Credit Card'),
        ('NET_BANKING', 'Net Banking'),
        ('WALLET', 'Wallet'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    
    # Order details
    order_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    
    # Payment gateway details
    transaction_id = models.CharField(max_length=255, blank=True, null=True)
    payg_order_id = models.CharField(max_length=255, blank=True, null=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True)
    
    # Status
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    
    # Additional info
    customer_name = models.CharField(max_length=255)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=15)
    
    # Metadata
    payment_gateway_response = models.JSONField(blank=True, null=True)
    webhook_response = models.JSONField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    payment_completed_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
    
    def __str__(self):
        return f"{self.order_id} - {self.amount} - {self.status}"


class PaymentWebhookLog(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='webhook_logs', null=True, blank=True)
    webhook_data = models.JSONField()
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Webhook - {self.created_at}"