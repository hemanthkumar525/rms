from django.db import models
from properties.models import LeaseAgreement, Property, BankAccount, PropertyUnit
from accounts.models import CustomUser, Tenant
from django.utils import timezone
from django.db import transaction
import json

# Create your models here.

class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    )

    PAYMENT_TYPE_CHOICES = (
        ('rent', 'Rent'),
        ('security_deposit', 'Security Deposit'),
        ('maintenance', 'Maintenance Fee'),
        ('late_fee', 'Late Fee'),
        ('subscription', 'Subscription'),
    )

    lease_agreement = models.ForeignKey(LeaseAgreement, on_delete=models.CASCADE, null=True, blank=True)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    payment_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=100, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=100,null=True, blank=True)
    stripe_payment_method_id = models.CharField(max_length=100,null=True, blank=True)
    paid_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.payment_type} - {self.lease_agreement.property.title if self.lease_agreement else 'Subscription'}"

    class Meta:
        ordering = ['-due_date']

class PaymentReminder(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE)
    reminder_date = models.DateField()
    is_sent = models.BooleanField(default=False)
    sent_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Reminder for {self.payment}"

class Invoice(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    )

    PAYMENT_TYPE_CHOICES = (
        ('rent', 'Rent'),
        ('security_deposit', 'Security Deposit'),
        ('maintenance', 'Maintenance Fee'),
    )

    lease_agreement = models.ForeignKey(
        LeaseAgreement,
        on_delete=models.CASCADE,
        related_name='lease_invoices'
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='property_invoices'
    )
    property_unit = models.ForeignKey(
        PropertyUnit,
        on_delete=models.CASCADE,
        related_name='unit_invoices'
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='tenant_invoices'
    )
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='rent')
    description = models.TextField(blank=True)
    due_date = models.DateField()
    issue_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_date = models.DateField(null=True, blank=True)
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_invoices')
    stripe_checkout_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    payment_url = models.URLField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} for {self.tenant}"

    def save(self, *args, **kwargs):
        # If this is a new invoice
        if not self.pk:
            # Set property and unit from lease agreement if not set
            if self.lease_agreement and not self.property:
                self.property = self.lease_agreement.property
            if self.lease_agreement and not self.property_unit:
                self.property_unit = self.lease_agreement.property_unit
            if self.lease_agreement and not self.tenant:
                self.tenant = self.lease_agreement.tenant

            # Calculate total amount
            if not self.total_amount:
                self.total_amount = self.amount + self.late_fee

        super().save(*args, **kwargs)

    def generate_payment_url(self, request=None):
        """Generate Stripe checkout session for the invoice"""
        if not self.bank_account or self.bank_account.account_type != 'Stripe':
            raise ValueError("Stripe payment method not configured for this invoice")

        import stripe
        from django.conf import settings
        from django.urls import reverse

        stripe.api_key = settings.STRIPE_SECRET_KEY

        success_url = request.build_absolute_uri(
            reverse('payments:payment_success', kwargs={'pk': self.pk})
        )
        cancel_url = request.build_absolute_uri(
            reverse('payments:invoice_detail', kwargs={'pk': self.pk})
        )

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': int(self.total_amount * 100),  # Convert to cents
                    'product_data': {
                        'name': f'Invoice #{self.invoice_number}',
                        'description': self.description or f'Payment for {self.payment_type}',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'invoice_id': self.id,
                'tenant_id': self.tenant.id,
                'property_id': self.property.id
            }
        )

        self.stripe_checkout_id = checkout_session.id
        self.payment_url = checkout_session.url
        self.save(update_fields=['stripe_checkout_id', 'payment_url'])
        return self.payment_url

    def mark_as_paid(self):
        """Mark the invoice as paid"""
        with transaction.atomic():
            self.status = 'paid'
            self.payment_date = timezone.now()
            self.save()
            return self