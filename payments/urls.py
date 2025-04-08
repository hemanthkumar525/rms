from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Payment URLs
    path('<int:pk>/', views.payment_detail, name='payment_detail'),
    path('webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('', views.PaymentListView.as_view(), name='payment_list_view'),
    path('create/', views.PaymentCreateView.as_view(), name='payment_create_view'),
    path('<int:pk>/', views.PaymentDetailView.as_view(), name='payment_detail_view'),
    path('<int:pk>/update/', views.PaymentUpdateView.as_view(), name='payment_update_view'),
    path('create-intent/<int:payment_id>/', views.create_payment_intent, name='create_payment_intent'),
    path('receipt/<int:pk>/', views.payment_receipt, name='payment_receipt'),
    path('payments/complete/', views.payment_complete, name='payment_complete'),
    path('payments/make/<int:lease_id>/', views.make_payment, name='make_payment'),
    path('payments/bulk-upload/', views.bulk_upload_payments, name='bulk_upload_payments'),
    
    # New Payment URLs
    path('cash-payment/<int:lease_agreement_id>/', views.confirm_cash_payment, name='confirm_cash_payment'),
    path('bank-transfer/<int:lease_agreement_id>/', views.confirm_bank_transfer, name='confirm_bank_transfer'),
    path('security-deposit/<int:lease_agreement_id>/', views.create_security_deposit_payment, name='create_security_deposit'),
    
    # Invoice URLs
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/create/', views.InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/update/', views.InvoiceUpdateView.as_view(), name='invoice_update'),
    path('invoices/<int:invoice_id>/pay/', views.tenant_make_payment, name='tenant_make_payment'),
    path('invoices/<int:pk>/success/', views.payment_success, name='payment_success'),
    
    # AJAX URLs
    path('get-lease-details/', views.get_lease_details, name='get_lease_details'),
]