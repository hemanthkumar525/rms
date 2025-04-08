from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from properties.models import LeaseAgreement, Invoice
from django.db.models import Q
import uuid

class Command(BaseCommand):
    help = 'Generate rent invoices for leases with upcoming due dates'

    def handle(self, *args, **options):
        # Get current date
        today = timezone.now().date()
        # Get date 5 days from now
        five_days_from_now = today + timedelta(days=5)
        
        # Find active leases where rent is due in 5 days
        leases = LeaseAgreement.objects.filter(
            Q(status='active') &
            Q(end_date__gte=today)
        )

        invoices_created = 0
        for lease in leases:
            # Calculate next rent due date
            next_due = lease.next_payment_date()
            
            # Check if this is 5 days before the due date
            if next_due == five_days_from_now:
                # Check if invoice doesn't already exist
                if not Invoice.objects.filter(
                    lease_agreement=lease,
                    due_date=next_due,
                    payment_type='rent'
                ).exists():
                    # Create invoice
                    invoice = Invoice.objects.create(
                        lease_agreement=lease,
                        property=lease.property,
                        tenant=lease.tenant,
                        invoice_number=f"RENT-{uuid.uuid4().hex[:8].upper()}",
                        amount=lease.monthly_rent,
                        payment_type='rent',
                        description=f"Monthly rent for {next_due.strftime('%B %Y')}",
                        due_date=next_due,
                        total_amount=lease.monthly_rent,
                        bank_account=lease.bank_account
                    )
                    invoices_created += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Created invoice {invoice.invoice_number} for lease {lease.id} - Due: {next_due}'
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {invoices_created} invoices'
            )
        )