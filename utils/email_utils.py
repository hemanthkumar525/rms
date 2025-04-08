from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string

def send_tenant_creation_email(tenant):
    """Send welcome email to newly created tenant"""
    subject = 'Welcome to RMS - Your Account Has Been Created'
    html_message = render_to_string('emails/tenant_welcome.html', {
        'tenant': tenant,
    })
    send_mail(
        subject=subject,
        message='',
        html_message=html_message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[tenant.user.email],
        fail_silently=False,
    )

def send_lease_creation_email(lease):
    """Send notification email when a new lease is created"""
    subject = 'New Lease Agreement Created'
    html_message = render_to_string('emails/lease_created.html', {
        'lease': lease,
    })
    # Send to both tenant and property owner
    recipient_list = [
        lease.tenant.user.email,
        lease.property.owner.user.email
    ]
    send_mail(
        subject=subject,
        message='',
        html_message=html_message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=recipient_list,
        fail_silently=False,
    )

def send_invoice_creation_email(invoice):
    """Send notification email when a new invoice is generated"""
    subject = 'New Invoice Generated'
    html_message = render_to_string('emails/invoice_created.html', {
        'invoice': invoice,
    })
    send_mail(
        subject=subject,
        message='',
        html_message=html_message,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[invoice.tenant.user.email],
        fail_silently=False,
    )