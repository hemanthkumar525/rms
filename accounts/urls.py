from django.urls import path, reverse_lazy
from . import views
from properties.views import overall_property_analytics
from django.contrib.auth import views as auth_views
from .views import UsernamePasswordResetView


app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),

    # Password Reset
    path('password-reset/',UsernamePasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(success_url=reverse_lazy('accounts:password_reset_complete')), name='password_reset_confirm'),
    path('reset/done/',auth_views.PasswordResetCompleteView.as_view(),name='password_reset_complete'),


    # User Type Selection
    path('select-user-type/', views.select_user_type, name='select_user_type'),

    # Registration
    path('register/property-owner/', views.register_property_owner, name='register_property_owner'),
    path('register/tenant/<int:property_id>/', views.register_tenant, name='register_tenant'),
    path('tenant_list/',views.tenant_list, name='tenant_list'),


    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    path('superadmin/dashboard/', views.superadmin_dashboard, name='superadmin_dashboard'),

    # Subscription Management

    path('subscription/edit/<int:package_id>/', views.subscription_edit, name='subscription_edit'),
    path('create_subscription/', views.create_subscription, name='create_subscription'),
    path('subscriptions/', views.subscription_list, name='subscription_list'),
    path('subscription/delete/<int:subscription_id>/',views.subscription_delete, name='subscription_delete'),
    path('subscription/upgrade/<int:subscription_id>/', views.upgrade_subscription, name='upgrade_subscription'),
    path('payment/', views.subscription_view, name='subscription'),
    path('stripe_webhook', views.stripe_webhook, name='stripe_webhook'),
    path('payment_successful/', views.payment_successful, name='payment_successful'),
    path('payment_cancelled/', views.payment_cancelled,name="payment_cancelled" ),

    #analytics
    path('property-analytics/', overall_property_analytics, name='property_analytics'),

    # Notifications
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/<int:notification_id>/mark-as-read/', views.mark_as_read, name='mark_as_read'),

    # Property Owner Management
    path('property-owner/<int:pk>/', views.property_owner_detail, name='property_owner_detail'),
    path('property-owner/<int:pk>/verify/', views.verify_property_owner, name='verify_property_owner'),
    path('property-owner/<int:pk>/delete/', views.delete_property_owner, name='delete_property_owner'),

    #password-reset
    path('password-reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]