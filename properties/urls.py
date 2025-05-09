from django.urls import path
from properties import views
from payments.views import invoice_list, confirm_cash_payment, confirm_bank_transfer, create_security_deposit_payment
app_name = 'properties'

urlpatterns = [
    # Property URLs
    path('', views.property_list, name='property_list'),
    path('create/', views.property_create, name='property_create'),
    path('<int:pk>/', views.property_detail, name='property_detail'),
    path('<int:pk>/edit/', views.property_edit, name='property_edit'),
    path('<int:pk>/delete/', views.property_delete, name='property_delete'),
    path('webhook/stripe/', views.stripe_webhook, name='stripe_webhook'),

    # Property Unit URLs
    path('<int:property_pk>/unit/create/', views.unit_create, name='unit_create'),
    path('<int:property_pk>/unit/<int:pk>/update/', views.unit_update, name='unit_update'),
    path('<int:property_pk>/unit/<int:pk>/delete/', views.unit_delete, name='unit_delete'),

    # Lease Agreement URLs
    path('lease/', views.lease_list, name='lease_list'),
    path('lease/<int:pk>/', views.lease_detail, name='lease_detail'),
    path('lease/<int:lease_id>/detail/', views.get_lease_details, name='get_lease_details'),
    path('<int:property_pk>/lease/create/', views.lease_agreement_create, name='lease_agreement_create'),
    path('lease/<int:pk>/update/', views.lease_agreement_update, name='lease_update'),
    path('<int:property_pk>/lease/<int:pk>/change-status/', views.lease_status_change, name='lease_status_change'),
    path('<int:property_pk>/lease/<int:pk>/delete/', views.lease_agreement_delete, name='lease_delete'),
    path('lease/<int:pk>/download/', views.download_lease, name='download_lease'),

    # Maintenance URLs
    path('maintenance/', views.maintenance_request_list, name='maintenance_request_list'),
    path('maintenance/select-unit/', views.maintenance_request_select_unit, name='maintenance_request_select_unit'),
    path('maintenance/create/<int:unit_pk>/unit', views.maintenance_request_create, name='maintenance_request_create'),
    path('maintenance/<int:pk>/', views.maintenance_request_detail, name='maintenance_request_detail'),
    path('maintenance/<int:pk>/change-status/', views.maintenance_request_change_status, name='maintenance_request_change_status'),

    # Invoice URLs
    path('invoices/', invoice_list, name='invoice_list'),
    path('<int:property_id>/invoice/select-lease/', views.select_lease_for_invoice, name='select_lease_for_invoice'),
    path('lease/<int:lease_id>/invoice/create/', views.invoice_create, name='invoice_create'),
    path('invoice/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoice/<int:pk>/update/', views.invoice_update, name='invoice_update'),
    path('invoice/<int:pk>/mark-paid/', views.mark_invoice_as_paid, name='mark_invoice_paid'),
    path('invoice/<int:pk>/pay/', views.tenant_make_payment, name='tenant_make_payment'),
    path('invoice/<int:pk>/payment/success/', views.payment_success, name='payment_success'),
    path('invoice/<int:pk>/download/', views.download_invoice, name='download_invoice'),

    # Bank Account URLs
    path('properties/<int:property_pk>/bank-accounts/<int:account_pk>/delete/', views.bank_account_delete, name='bank_account_delete'),
    path('<int:property_pk>/bank-account/<int:pk>/edit/', views.bank_account_edit, name='bank_account_edit'),
    path('<int:property_pk>/bank-account/create/', views.bank_account_create, name='bank_account_create'),

    #new payment
    path('cash-payment/<int:lease_agreement_id>/', confirm_cash_payment, name='confirm_cash_payment'),
    path('bank-transfer/<int:lease_agreement_id>/', confirm_bank_transfer, name='confirm_bank_transfer'),
    path('security-deposit/<int:lease_agreement_id>/', create_security_deposit_payment, name='create_security_deposit'),

    # Property Manager URLs
    path('property-managers/', views.property_manager_list, name='property_manager_list'),
    path('property-managers/create/', views.property_manager_create, name='property_manager_create'),
    path('property-managers/<int:pk>/edit/', views.property_manager_edit, name='property_manager_edit'),
    path('property-managers/<int:pk>/delete/', views.property_manager_delete, name='property_manager_delete'),

    # Tenant URLs
    path('tenant/<int:tenant_pk>/delete/', views.tenant_delete, name='tenant_delete'),
    path('tenant/<int:tenant_pk>/edit/', views.tenant_edit, name='tenant_edit'),

    #property analytics
    path('property-analytics/', views.property_analytics, name='property_analytics'),

]