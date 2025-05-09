from email.policy import default
from django.db import models
from accounts.models import PropertyOwner, Tenant, CustomUser
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db import transaction
import uuid

# Create your models here.

class Property(models.Model):
    PROPERTY_TYPE_CHOICES = (
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),

    )

    owner = models.ForeignKey(PropertyOwner, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    is_available = models.BooleanField(default=True)
    is_occupied = models.BooleanField(default=False)
    postal_code = models.CharField(max_length=10)
    description = models.TextField(blank=True)  # Add back description field
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_available_account_types(self):
        """Get payment gateway types available for this property"""
        return BankAccount.ACCOUNT_TYPES

    @property
    def active_leases_count(self):
        """Returns the count of active lease agreements for this property"""
        return self.leaseagreement_set.filter(status='active').count()

    @property
    def occupancy_rate(self):
        """Calculate the occupancy rate based on units that are not available"""
        total_units = self.units.count()
        if total_units == 0:
            return 0
        occupied_units = self.units.filter(is_available=False).count()
        return round((occupied_units / total_units) * 100)

    def __str__(self):
        return self.title



    # Keep only property-wide fields

class PropertyUnit(models.Model):

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='units')
    unit_number = models.CharField(max_length=20)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    bedrooms = models.PositiveIntegerField()
    bathrooms = models.PositiveIntegerField()
    square_feet = models.PositiveIntegerField()
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    business_type = models.CharField(max_length=20, blank=True, null=True)
    kitchen = models.PositiveIntegerField(default=0)


    def __str__(self):
        return f"{self.property.title} - {self.unit_number}"



class PropertyImage(models.Model):
    property = models.ForeignKey(Property, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='property_images/')
    caption = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Image for {self.property.title}"


class BankAccount(models.Model):


    ACCOUNT_TYPES = (
        ('Paypal', 'Paypal'),
        ('Stripe', 'Stripe'),
    )

    STATUS_CHOICES = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )

    MODE_CHOICES = (
        ('Sandbox', 'Sandbox'),
        ('Live', 'Live'),
    )
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='bank_accounts')
    title = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    account_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='Sandbox')
    client_id = models.CharField(max_length=255)
    secret_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.account_type}"

    class Meta:
        ordering = ['-created_at']





class LeaseAgreement(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('terminated', 'Terminated'),
        ('expired', 'Expired'),
    )

    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2)
    rent_due_day = models.PositiveIntegerField(
        help_text="Day of the month when rent is due (1-31)",
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        default=1
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,default='pending')
    terms_and_conditions = models.TextField()
    signed_by_tenant = models.BooleanField(default=False)
    signed_by_owner = models.BooleanField(default=False)
    document = models.FileField(upload_to='lease_documents/', null=True, blank=True)
    property_unit = models.ForeignKey(PropertyUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name='lease_agreements')
    created_at = models.DateTimeField(auto_now_add=True)

    def next_payment_date(self):
        """Calculate the next payment due date"""
        today = timezone.now().date()
        current_month = today.replace(day=self.rent_due_day)

        if today > current_month:
            # If we've passed the due day this month, payment is due next month
            if current_month.month == 12:
                next_payment = current_month.replace(year=current_month.year + 1, month=1)
            else:
                next_payment = current_month.replace(month=current_month.month + 1)
        else:
            # If we haven't reached the due day yet, payment is due this month
            next_payment = current_month

        return next_payment

    def __str__(self):
        return f"Lease for {self.property.title} - {self.tenant.user.get_full_name()}"


class TenantProperty(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    )

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='tenant_properties')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='property_tenants')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Tenant Properties"
        ordering = ['-created_at']
        unique_together = ['tenant', 'property']  # Prevent duplicate tenant-property relationships

    def __str__(self):
        return f"{self.tenant.user.email} - {self.property.title}"

    def get_status_active(self):
        return self.status == 'active'


class PropertyMaintenance(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )

    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    property_unit = models.ForeignKey(PropertyUnit, on_delete=models.CASCADE, related_name='maintenance_requests',null=True,blank=True)
    reported_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')])
    reported_date = models.DateTimeField(auto_now_add=True)
    resolved_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} - {self.property.title}"


class PropertyManager(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    assigned_properties = models.ManyToManyField(Property, related_name='property_managers')
    maintenance_requests = models.ManyToManyField(PropertyMaintenance, related_name='assigned_managers')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} - Property Manager"

    class Meta:
        verbose_name = 'Property Manager'
        verbose_name_plural = 'Property Managers'
        ordering = ['-created_at']
