from rest_framework import serializers
from .models import Payment

class PaymentInitiateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id', 'order_id', 'amount', 'currency', 'status',
            'payment_method', 'transaction_id', 'customer_name',
            'customer_email', 'customer_phone', 'created_at',
            'payment_completed_at'
        ]
        read_only_fields = ['id', 'order_id', 'created_at']

class PaymentStatusSerializer(serializers.Serializer):
    order_id = serializers.CharField()
    status = serializers.CharField()
    transaction_id = serializers.CharField(required=False)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)