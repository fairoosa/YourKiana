import hashlib
import hmac
import json
import requests
import base64
from datetime import datetime
from django.conf import settings

class PayGPaymentGateway:
    def __init__(self):
        self.config = settings.PAYG_CONFIG
        self.merchant_key_id = self.config['MERCHANT_KEY_ID']
        self.mid = self.config['MID']
        # Remove 0x prefix if present
        self.auth_key = self.config['AUTHENTICATION_KEY']
        self.auth_token = self.config['AUTHENTICATION_TOKEN']   
        self.payment_url = self.config['PAYMENT_URL']
    
    def generate_basic_auth(self):
        """Generate Basic Authentication header for PayG"""
        # Format: ::M:
        auth_string = f"{self.auth_key}:{self.auth_token}:M:{self.mid}"
        
        # Encode to base64
        encoded = base64.b64encode(auth_string.encode()).decode()
        
        return f"basic {encoded}"  # lowercase 'basic' as per PayG docs
    
    def create_payment_request(self, payment_data):
        """
        Create payment request to PayG
        
        payment_data should contain:
        - order_id
        - amount
        - customer_name
        - customer_email
        - customer_phone
        - callback_url
        - return_url
        """
        
        # Get current datetime in PayG format (YYYYMMDD)
        current_datetime = datetime.now().strftime('%Y%m%d')
        
        # Prepare payment payload according to PayG format
        payload = {
            "MID": self.mid,
            "UniqueRequestId": payment_data['order_id'],
            "ProductData": json.dumps({
                "ProductName": "YourKirana Order",
                "ProductInfo": f"Order {payment_data['order_id']}",
                "ProductPrice": str(payment_data['amount'])
            }),
            "RequestDateTime": current_datetime,
            "RedirectUrl": payment_data['return_url'],
            "TransactionData": {
                "AcceptedPaymentTypes": "",
                "PaymentType": "",
                "SurchargeType": "",
                "SurchargeValue": "",
                "RefTransactionId": "",
                "IndustrySpecificationCode": "",
                "PartialPaymentOption": ""
            },
            "OrderAmount": str(payment_data['amount']),
            "OrderType": "ONLINE",
            "OrderAmountData": {
                "AmountTypeDesc": "",
                "Amount": ""
            },
            "CustomerData": {
                "CustomerId": str(payment_data.get('user_id', '')),
                "CustomerNotes": "Order from YourKirana",
                "FirstName": payment_data['customer_name'].split()[0] if payment_data['customer_name'] else '',
                "LastName": ' '.join(payment_data['customer_name'].split()[1:]) if len(payment_data['customer_name'].split()) > 1 else '',
                "MobileNo": payment_data['customer_phone'],
                "Email": payment_data['customer_email'],
                "EmailReceipt": "true",
                "BillingAddress": "",
                "BillingCity": "",
                "BillingState": "",
                "BillingCountry": "India",
                "BillingZipCode": "",
                "ShippingFirstName": payment_data['customer_name'].split()[0] if payment_data['customer_name'] else '',
                "ShippingLastName": ' '.join(payment_data['customer_name'].split()[1:]) if len(payment_data['customer_name'].split()) > 1 else '',
                "ShippingAddress": "",
                "ShippingCity": "",
                "ShippingState": "",
                "ShippingCountry": "India",
                "ShippingZipCode": "",
                "ShippingMobileNo": payment_data['customer_phone'],
                "ShippingEmail": payment_data['customer_email']
            }
        }
        
        # Generate Basic Auth header
        auth_header = self.generate_basic_auth()
        
        # Send request to PayG
        headers = {
            'Content-Type': 'application/json',
            'Authorization': auth_header,
            'cache-control': 'no-cache'
        }
        
        try:
            print(f"Sending request to PayG: {self.payment_url}")
            print(f"Headers: {headers}")
            print(f"Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(
                self.payment_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            print(f"Response Status: {response.status_code}")
            print(f"Response Body: {response.text}")
            
            if response.status_code == 200 or response.status_code == 201:
                response_data = response.json()
                return {
                    'success': True,
                    'data': response_data
                }
            else:
                error_detail = response.text if response.text else 'No error details provided'
                return {
                    'success': False,
                    'error': f"Payment gateway error: {response.status_code}",
                    'data': error_detail
                }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f"Request failed: {str(e)}"
            }
    
    def verify_webhook_signature(self, webhook_data, signature):
        """Verify webhook signature from PayG (if provided)"""
        # Implement if PayG provides signature verification
        return True