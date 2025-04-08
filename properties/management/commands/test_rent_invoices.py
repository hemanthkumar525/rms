# Create test_rent_invoices.py in properties/management/commands/
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from properties.models import Property, LeaseAgreement, Tenant, BankAccount

class Command(BaseCommand):
    help = 'Create a test lease agreement for invoice generation'

    def handle(self, *args, **options):
        # Get first property and tenant (or create them)
        property = Property.objects.first()
        tenant = Tenant.objects.first()
        bank_account = BankAccount.objects.filter(property=property).first()
        
        if not all([property, tenant, bank_account]):
            self.stdout.write(self.style.ERROR('Please create property, tenant and bank account first'))
            return
        
        # Create lease agreement with rent due in 5 days
        today = timezone.now().date()
        five_days_from_now = today + timedelta(days=5)
        
        lease = LeaseAgreement.objects.create(
            property=property,
            tenant=tenant,
            bank_account=bank_account,
            start_date=today,
            end_date=today + timedelta(days=365),
            monthly_rent=1000.00,
            security_deposit=2000.00,
            rent_due_day=five_days_from_now.day,  # Set due day to 5 days from now
            status='active',
            terms_and_conditions='Test lease agreement',
            signed_by_tenant=True,
            signed_by_owner=True
        )
        
        self.stdout.write(self.style.SUCCESS(f'Created test lease agreement with ID: {lease.id}'))
        self.stdout.write(self.style.SUCCESS(f'Next payment date: {lease.next_payment_date()}'))