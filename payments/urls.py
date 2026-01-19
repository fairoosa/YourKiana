from django.urls import path
from .views import (
    InitiatePaymentView,
    PaymentWebhookView,
    PaymentStatusView,
    PaymentHistoryView,
    PaymentVerifyView
)


urlpatterns = [
    path('initiate/', InitiatePaymentView.as_view(), name='payment_initiate'),
    path('webhook/', PaymentWebhookView.as_view(), name='payment_webhook'),
    path('status/', PaymentStatusView.as_view(), name='payment_status'),
    path('history/', PaymentHistoryView.as_view(), name='payment_history'),
    path('verify/', PaymentVerifyView.as_view(), name='payment_verify'),
]