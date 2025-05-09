from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta

class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('superadmin', 'Super Admin'),
        ('property_owner', 'Property Owner'),
        ('tenant', 'Tenant'),
        ('property_manager', 'Property Manager')
    )

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES)
    phone_number = models.CharField(max_length=15)
    address = models.TextField()
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)

    def is_superadmin(self):
        return self.user_type == 'superadmin'

    def is_property_owner(self):
        return self.user_type == 'property_owner'

    def is_tenant(self):
        return self.user_type == 'tenant'

    def is_property_manager(self):
        return self.user_type == 'property_manager'

class PropertyOwner(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    verification_status = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.company_name}"

class Tenant(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    emergency_contact = models.CharField(max_length=100)
    employment_info = models.TextField(blank=True)
    id_proof = models.FileField(upload_to='tenant_docs/', null=True)

    def __str__(self):
        return self.user.get_full_name()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.get_full_name()

    class Meta:
        ordering = ['-created_at']



class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.message[:20]} - {'Read' if self.is_read else 'Unread'}"


class Subscription(models.Model):
    SUBSCRIPTION_TYPES = (
        ('basic', 'Basic'),
        ('premium', 'Premium'),
        ('enterprise', 'Enterprise'),
    )

    name = models.CharField(max_length=50)
    type = models.CharField(max_length=20, choices=SUBSCRIPTION_TYPES,default='basic')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_price_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    max_properties = models.IntegerField()
    max_units = models.IntegerField()
    description = models.TextField()
    features = models.JSONField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    duration_months = models.PositiveIntegerField(help_text="Duration in months",default=1)
    max_units = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.name} - ₹{self.price}"

class PropertyOwnerSubscription(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded')
    )

    property_owner = models.ForeignKey(PropertyOwner, on_delete=models.CASCADE)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    payment_id = models.CharField(max_length=100, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    payment_date = models.DateTimeField(null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_payment_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, null=True, blank=True)
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.property_owner.user.email} - {self.subscription.name}"

    def is_active(self):
        return self.status == 'active' and self.end_date > timezone.now()

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.start_date + timedelta(days=30 * self.subscription.duration_months)
        super().save(*args, **kwargs)
