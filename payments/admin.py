from django.contrib import admin
from .models import Payment, PaymentWebhookLog




@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'user', 'amount', 'status', 'payment_method', 'created_at')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('order_id', 'transaction_id', 'user__email', 'customer_email')
    readonly_fields = ('id', 'created_at', 'updated_at', 'payment_completed_at')
    
    fieldsets = (
        ('Order Information', {
            'fields': ('id', 'user', 'order_id', 'amount', 'currency')
        }),
        ('Customer Details', {
            'fields': ('customer_name', 'customer_email', 'customer_phone')
        }),
        ('Payment Gateway', {
            'fields': ('transaction_id', 'payg_order_id', 'payment_method', 'status')
        }),
        ('Responses', {
            'fields': ('payment_gateway_response', 'webhook_response'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'payment_completed_at')
        }),
    )

@admin.register(PaymentWebhookLog)
class PaymentWebhookLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'payment', 'processed', 'created_at')
    list_filter = ('processed', 'created_at')
    search_fields = ('payment__order_id',)
    readonly_fields = ('created_at',)