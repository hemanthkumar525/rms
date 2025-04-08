from django.core.exceptions import ValidationError
from accounts.models import PropertyOwnerSubscription
from django.utils import timezone
from django.db import transaction
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
from django.contrib import messages

def verify_subscription_and_limit(property_owner, request=None):
    """
    Verify if property owner has an active subscription and hasn't exceeded property limits.
    Returns the active subscription if valid, otherwise adds error message and returns None.
    """
    active_subscription = PropertyOwnerSubscription.objects.filter(
        property_owner=property_owner,
        status='active',
        end_date__gt=timezone.now()
    ).first()
    
    if not active_subscription and request:
        messages.error(request, "No active subscription found. Please subscribe to a plan.")
        return None
    elif not active_subscription:
        raise ValidationError("No active subscription found. Please subscribe to a plan.")
    
    return active_subscription

def check_property_limit(property_owner, request=None):
    """
    Check if property owner has reached their subscription property limit.
    Returns True if within limit, otherwise adds error message and returns False.
    """
    active_subscription = verify_subscription_and_limit(property_owner, request)
    if not active_subscription:
        return False
    
    # Get count of current active properties
    current_properties = property_owner.property_set.filter(is_available=True).count()
    
    # Check if adding one more property would exceed the limit
    if current_properties + 1 > active_subscription.subscription.max_properties:
        if request:
            messages.error(
                request,
                f"You have reached your subscription limit of {active_subscription.subscription.max_properties} properties. "
                "Please upgrade your subscription to add more properties."
            )
            return False
        else:
            raise ValidationError(
                f"You have reached your subscription limit of {active_subscription.subscription.max_properties} properties. "
                "Please upgrade your subscription to add more properties."
            )
    return True

def save_property_with_limit_check(property_obj, request=None):
    """
    Save a property while checking subscription limits.
    Returns True if saved successfully, adds error message and returns False if limit exceeded.
    """
    with transaction.atomic():
        # First verify subscription and check limits
        if not check_property_limit(property_obj.owner, request):
            return False
        
        # If checks pass, save the property
        property_obj.save()
        return True

def check_unit_limit(property, request=None):
    """
    Check if property has reached subscription unit limit.
    Returns True if within limit, otherwise adds error message and returns False.
    """
    # First verify the property owner's subscription
    active_subscription = verify_subscription_and_limit(property.owner, request)
    if not active_subscription:
        return False
    
    current_units = property.units.count()
    if current_units >= active_subscription.subscription.max_units:
        if request:
            messages.error(
                request,
                f"You have reached your subscription limit of {active_subscription.subscription.max_units} units per property. "
                "Please upgrade your subscription to add more units."
            )
            return False
        else:
            raise ValidationError(
                f"You have reached your subscription limit of {active_subscription.subscription.max_units} units per property. "
                "Please upgrade your subscription to add more units."
            )
    return True

def send_maintenance_request_notification(maintenance_request, request=None):
    """
    Send email notifications for maintenance requests.
    Returns True if sent successfully, adds error message and returns False if failed.
    """
    try:
        # Email to property owner
        owner_subject = f'New Maintenance Request - {maintenance_request.property.title}'
        owner_html_message = render_to_string('emails/maintenance_request_owner.html', {
            'request': maintenance_request,
            'property': maintenance_request.property,
            'tenant': maintenance_request.tenant
        })
        owner_plain_message = strip_tags(owner_html_message)
        
        send_mail(
            subject=owner_subject,
            message=owner_plain_message,
            html_message=owner_html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[maintenance_request.property.owner.user.email],
            fail_silently=False,
        )

        # Confirmation email to tenant
        tenant_subject = 'Maintenance Request Submitted Successfully'
        tenant_html_message = render_to_string('emails/maintenance_request_tenant.html', {
            'request': maintenance_request,
            'property': maintenance_request.property
        })
        tenant_plain_message = strip_tags(tenant_html_message)
        
        send_mail(
            subject=tenant_subject,
            message=tenant_plain_message,
            html_message=tenant_html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[maintenance_request.tenant.user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        if request:
            messages.error(request, "Failed to send maintenance request notification.")
        else:
            raise ValidationError("Failed to send maintenance request notification.")
        return False

def send_invoice_notification(invoice, request=None):
    """
    Send email notifications for new invoices.
    Returns True if sent successfully, adds error message and returns False if failed.
    """
    try:
        subject = f'New Invoice - {invoice.property.title}'
        html_message = render_to_string('emails/invoice_notification.html', {
            'invoice': invoice,
            'property': invoice.property,
            'tenant': invoice.tenant
        })
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invoice.tenant.user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        if request:
            messages.error(request, "Failed to send invoice notification.")
        else:
            raise ValidationError("Failed to send invoice notification.")
        return False

def send_lease_notification(lease, request=None):
    """
    Send email notifications for lease creation/updates.
    Returns True if sent successfully, adds error message and returns False if failed.
    """
    try:
        # Email to tenant
        tenant_subject = f'New Lease Agreement - {lease.property.title}'
        tenant_html_message = render_to_string('emails/lease_notification_tenant.html', {
            'lease': lease,
            'property': lease.property,
            'owner': lease.property.owner
        })
        tenant_plain_message = strip_tags(tenant_html_message)
        
        send_mail(
            subject=tenant_subject,
            message=tenant_plain_message,
            html_message=tenant_html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[lease.tenant.user.email],
            fail_silently=False,
        )

        # Confirmation email to property owner
        owner_subject = f'Lease Agreement Created - {lease.property.title}'
        owner_html_message = render_to_string('emails/lease_notification_owner.html', {
            'lease': lease,
            'property': lease.property,
            'tenant': lease.tenant
        })
        owner_plain_message = strip_tags(owner_html_message)
        
        send_mail(
            subject=owner_subject,
            message=owner_plain_message,
            html_message=owner_html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[lease.property.owner.user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        if request:
            messages.error(request, "Failed to send lease notification.")
        else:
            raise ValidationError("Failed to send lease notification.")
        return False