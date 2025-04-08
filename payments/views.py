from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.utils import timezone
from django.http import JsonResponse, HttpResponseForbidden
from django.conf import settings
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse_lazy
import stripe


from .models import Payment, Invoice
from .forms import PaymentForm, PaymentListForm
from properties.models import Property
from accounts.models import PropertyOwner, Tenant

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
import csv
from rms.settings import *
from io import BytesIO
from datetime import datetime, timedelta
from .forms import (
    PaymentFilterForm, 
    BulkUploadForm,
    PaymentConfirmationForm,
    InvoiceForm,
    InvoiceFilterForm
)
from accounts.models import CustomUser

stripe.api_key = STRIPE_SECRET_KEY

class PaymentListView(LoginRequiredMixin, ListView):
    model = Invoice
    template_name = 'payments/payment_list.html'
    context_object_name = 'invoices'
    paginate_by = 10

    def get_queryset(self):
        queryset = Invoice.objects.all()
        
        # Filter based on user role
        if self.request.user.is_property_owner:
            queryset = queryset.filter(property__owner=self.request.user.propertyowner)
        elif self.request.user.is_tenant:
            queryset = queryset.filter(tenant=self.request.user.tenant)

        # Order by due date (most recent first)
        return queryset.order_by('-due_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()
        
        # Add summary statistics
        total_amount = queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        pending_amount = queryset.filter(status='pending').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        completed_amount = queryset.filter(status='paid').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        context.update({
            'total_amount': total_amount,
            'pending_amount': pending_amount,
            'completed_amount': completed_amount,
            'total_count': queryset.count(),
            'pending_count': queryset.filter(status='pending').count(),
            'completed_count': queryset.filter(status='paid').count(),
        })
        
        return context

class PaymentDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Payment
    template_name = 'payments/payment_detail.html'
    context_object_name = 'payment'

    def test_func(self):
        payment = self.get_object()
        user = self.request.user
        return (user.is_superadmin or 
                (user.is_property_owner and payment.lease_agreement.property.owner == user.propertyowner) or
                (user.is_tenant and payment.lease_agreement.tenant == user.tenant))

class PaymentCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = 'payments/payment_form.html'
    success_url = reverse_lazy('payments:payment_list')

    def test_func(self):
        return self.request.user.is_superadmin or self.request.user.is_property_owner

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.created_by = self.request.user
        payment.save()
        
        # Create payment history
        PaymentHistory.objects.create(
            payment=payment,
            user=self.request.user,
            action='CREATED',
            description='Payment created'
        )
        
        messages.success(self.request, 'Payment created successfully.')
        return super().form_valid(form)

class PaymentUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = 'payments/payment_form.html'
    success_url = reverse_lazy('payments:payment_list')

    def test_func(self):
        payment = self.get_object()
        user = self.request.user
        return (user.is_superadmin or 
                (user.is_property_owner and payment.lease_agreement.property.owner == user.propertyowner))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        payment = form.save()
        
        # Create payment history
        PaymentHistory.objects.create(
            payment=payment,
            user=self.request.user,
            action='UPDATED',
            description='Payment details updated'
        )
        
        messages.success(self.request, 'Payment updated successfully.')
        return super().form_valid(form)

@login_required
def create_payment_intent(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id)

    # Verify tenant authorization
    if not request.user.is_tenant:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(payment.amount * 100),
            currency='usd',
            payment_method_types=['card', 'us_bank_account'],
            metadata={
                'payment_id': payment.id,
                'lease_id': payment.lease_agreement.id,
                'tenant_id': request.user.id,
                'property_id': payment.lease_agreement.property.id
                }
                )
        payment.stripe_payment_intent_id = intent.id
        payment.save()
        

        return JsonResponse({
            'clientSecret': intent.client_secret,
            'payment_id': payment.id
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
def stripe_webhook(request):
    webhook_secret = STRIPE_WEBHOOK_SECRET
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        return HttpResponse(status=400)

    if event['type'] == 'payment_intent.succeeded':
        intent = event['data']['object']
        payment_id = intent['metadata']['payment_id']
        payment = Payment.objects.get(id=payment_id)
        
        # Update payment status
        payment.status = 'completed'
        payment.payment_date = timezone.now()
        payment.transaction_id = intent['id']
        payment.payment_method = 'stripe'
        payment.save()
        
        # Create payment history
        payment = Payment.objects.create(
            lease_agreement=payment.lease_agreement,
            payment_type='rent',
            amount=payment.amount,
            due_date=payment.due_date,
            payment_date=timezone.now(),
            status='completed',
            payment_method='stripe',
            transaction_id=intent['id'],
            paid_by=payment.paid_by
        )
        
        # Create payment history
        PaymentHistory.objects.create(
            payment=payment,
            user=payment.paid_by,
            action='COMPLETED',
            description='Payment completed via Stripe'
        )
    
    elif event['type'] == 'payment_intent.payment_failed':
        intent = event['data']['object']
        payment_id = intent['metadata']['payment_id']
        payment = Payment.objects.get(id=payment_id)
        
        # Update payment status
        payment.status = 'failed'
        payment.save()
        
        # Create payment history
        PaymentHistory.objects.create(
            payment=payment,
            user=payment.paid_by,
            action='FAILED',
            description='Payment failed via Stripe'
        )

    return HttpResponse(status=200)

@login_required
def make_payment(request, lease_id):
    lease = get_object_or_404(LeaseAgreement, id=lease_id)
    
    # Verify that the logged-in user is the tenant
    if not request.user.is_tenant or request.user.tenant != lease.tenant:
        messages.error(request, 'You are not authorized to make payments for this lease.')
        return redirect('payments:payment_list')
    
    # Create a new payment for this lease if it doesn't exist
    payment = Payment.objects.create(
        lease_agreement_id=lease.id,
        due_date=timezone.now(),
        amount=lease.monthly_rent,
        status='PENDING',
        payment_method='STRIPE',
    )
    
    return render(request, 'payments/make_payment.html', {
        'payment': payment,
        'stripe_public_key': STRIPE_PUBLIC_KEY,
        'lease': lease
    })

@login_required
def confirm_payment(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    
    # Verify that the logged-in user is the property owner
    if not (request.user.is_superadmin or 
            (request.user.is_property_owner and payment.lease_agreement.property.owner == request.user.propertyowner)):
        messages.error(request, 'You are not authorized to confirm this payment.')
        return redirect('payments:payment_list')
    
    if request.method == 'POST':
        form = PaymentConfirmationForm(request.POST)
        if form.is_valid():
            payment.status = 'PAID'
            payment.confirmed_at = timezone.now()
            payment.confirmed_by = request.user
            payment.save()
            
            # Create payment history
            PaymentHistory.objects.create(
                payment=payment,
                user=request.user,
                action='CONFIRMED',
                description='Payment confirmed by property owner'
            )
            
            messages.success(request, 'Payment confirmed successfully.')
            return redirect('payments:payment_detail', pk=payment.pk)
    
    return redirect('payments:payment_detail', pk=payment.pk)

@login_required
def payment_receipt(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    
    # Verify user authorization
    if not (request.user.is_superadmin or 
            request.user.is_property_owner or 
            request.user.tenant == payment.lease_agreement.tenant):
        messages.error(request, 'You are not authorized to view this receipt.')
        return redirect('payments:payment_list')
    
    return render(request, 'payments/payment_receipt.html', {
        'payment': payment
    })

@login_required
def bulk_upload_payments(request):
    if not (request.user.is_superadmin or request.user.is_property_owner):
        messages.error(request, 'You are not authorized to perform bulk uploads.')
        return redirect('payments:payment_list')
    
    if request.method == 'POST':
        form = BulkUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            property_id = form.cleaned_data['property']
            
            try:
                # Process CSV file
                decoded_file = file.read().decode('utf-8').splitlines()
                reader = csv.DictReader(decoded_file)
                
                success_count = 0
                error_count = 0
                errors = []
                
                for row in reader:
                    try:
                        # Create payment record
                        payment = Payment.objects.create(
                            lease_agreement=LeaseAgreement.objects.get(
                                property_id=property_id,
                                tenant__user__email=row['tenant_email']
                            ),
                            amount=float(row['amount']),
                            payment_date=datetime.strptime(row['payment_date'], '%Y-%m-%d'),
                            payment_method=row['payment_method'],
                            status='PENDING',
                            created_by=request.user
                        )
                        success_count += 1
                    except Exception as e:
                        error_count += 1
                        errors.append(f"Row {reader.line_num}: {str(e)}")
                
                messages.success(
                    request,
                    f'Bulk upload completed. {success_count} payments created successfully. '
                    f'{error_count} errors encountered.'
                )
                if errors:
                    messages.warning(request, 'Errors: ' + '; '.join(errors))
                
                return redirect('payments:payment_list')
            
            except Exception as e:
                messages.error(request, f'Error processing file: {str(e)}')
    else:
        form = BulkUploadForm()
    
    return render(request, 'payments/bulk_upload.html', {
        'form': form
    })

@login_required
def export_payments(request, format='csv'):
    if not (request.user.is_superadmin or request.user.is_property_owner):
        messages.error(request, 'You are not authorized to export payments.')
        return redirect('payments:payment_list')
    
    # Get filtered queryset
    queryset = Payment.objects.all()
    if request.user.is_property_owner:
        queryset = queryset.filter(lease_agreement__property__owner=request.user.propertyowner)
    
    # Apply filters from URL parameters
    form = PaymentFilterForm(request.GET)
    if form.is_valid():
        if form.cleaned_data.get('status'):
            queryset = queryset.filter(status=form.cleaned_data['status'])
        if form.cleaned_data.get('payment_method'):
            queryset = queryset.filter(payment_method=form.cleaned_data['payment_method'])
        if form.cleaned_data.get('start_date'):
            queryset = queryset.filter(payment_date__gte=form.cleaned_data['start_date'])
        if form.cleaned_data.get('end_date'):
            queryset = queryset.filter(payment_date__lte=form.cleaned_data['end_date'])
    
    # Prepare the response
    if format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="payments.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Property', 'Tenant', 'Amount', 'Status', 'Payment Method',
            'Payment Date', 'Reference Number', 'Created At'
        ])
        
        for payment in queryset:
            writer.writerow([
                payment.id,
                payment.lease_agreement.property.title,
                payment.lease_agreement.tenant.user.get_full_name(),
                payment.amount,
                payment.get_status_display(),
                payment.get_payment_method_display(),
                payment.payment_date,
                payment.reference_number,
                payment.created_at
            ])
    
    else:  # Excel format
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet()
        
        # Add headers
        headers = [
            'ID', 'Property', 'Tenant', 'Amount', 'Status', 'Payment Method',
            'Payment Date', 'Reference Number', 'Created At'
        ]
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)
        
        # Add data
        for row, payment in enumerate(queryset, start=1):
            worksheet.write(row, 0, payment.id)
            worksheet.write(row, 1, payment.lease_agreement.property.title)
            worksheet.write(row, 2, payment.lease_agreement.tenant.user.get_full_name())
            worksheet.write(row, 3, float(payment.amount))
            worksheet.write(row, 4, payment.get_status_display())
            worksheet.write(row, 5, payment.get_payment_method_display())
            worksheet.write(row, 6, payment.payment_date.strftime('%Y-%m-%d'))
            worksheet.write(row, 7, payment.reference_number or '')
            worksheet.write(row, 8, payment.created_at.strftime('%Y-%m-%d %H:%M:%S'))
        
        workbook.close()
        output.seek(0)
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="payments.xlsx"'
    
    return response

@login_required
def payment_complete(request):
    payment_intent_id = request.GET.get('payment_intent')
    payment_intent_client_secret = request.GET.get('payment_intent_client_secret')
    
    if not payment_intent_id:
        messages.error(request, 'No payment information found.')
        return redirect('payments:payment_list')
    
    try:
        # Retrieve the payment intent from Stripe
        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        
        # Find the corresponding payment in our database
        payment = Payment.objects.get(stripe_payment_intent_id=payment_intent_id)
        
        if payment_intent.status == 'succeeded':
            # Update payment status
            payment.status = 'completed'
            payment.payment_date = timezone.now()
            payment.transaction_id = payment_intent_id
            payment.payment_method = 'stripe'
            payment.save()
            
            # Create payment history
            PaymentHistory.objects.create(
                payment=payment,
                user=request.user,
                action='COMPLETED',
                description='Payment completed via Stripe'
            )
            
            messages.success(request, 'Payment completed successfully!')
        else:
            messages.error(request, 'Payment was not successful. Please try again.')
            
        return redirect('payments:payment_detail', pk=payment.id)
        
    except stripe.error.StripeError as e:
        messages.error(request, f'Payment error: {str(e)}')
        return redirect('payments:payment_list')
    except Payment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('payments:payment_list')

@login_required
def payment_detail(request, pk):
    # Retrieve the payment object by primary key (id)
    payment = get_object_or_404(Payment, pk=pk)
    
    user = request.user
    
    # Authorization check: user must be a superadmin, property owner, or the tenant who made the payment
    if not (
        user.is_superadmin or 
        (user.is_property_owner and payment.lease_agreement.property.owner == user.propertyowner) or
        (user.is_tenant and payment.lease_agreement.tenant == user.tenant)
    ):
        messages.error(request, 'You are not authorized to view this payment.')
        return redirect('payments:payment_list')

    # Prepare context data for the template
    context = {
        'payment': payment,
        'lease': payment.amount,
    }

    return render(request, 'payments/payment_detail.html', context)

@login_required
def invoice_list(request):
    """View for listing invoices"""
    if hasattr(request.user, 'tenant'):
        invoices = Invoice.objects.filter(tenant=request.user.tenant)
    elif hasattr(request.user, 'propertyowner'):
        invoices = Invoice.objects.filter(property__owner=request.user.propertyowner)
    else:
        invoices = Invoice.objects.none()
    
    return render(request, 'payments/invoice_list.html', {
        'invoices': invoices
    })

@login_required
def invoice_detail(request, pk):
    """View for showing invoice details"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    # Check permissions
    if not (hasattr(request.user, 'tenant') and request.user.tenant == invoice.tenant) and \
       not (hasattr(request.user, 'propertyowner') and request.user.propertyowner == invoice.property.owner):
        return HttpResponseForbidden("You don't have permission to view this invoice")
    
    return render(request, 'payments/invoice_detail.html', {
        'invoice': invoice,
        'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY
    })

class InvoiceListView(LoginRequiredMixin, ListView):
    model = Invoice
    template_name = 'payments/invoice_list.html'
    context_object_name = 'invoices'
    paginate_by = 10

    def get_queryset(self):
        queryset = Invoice.objects.all()
        
        # Filter based on user role
        if self.request.user.is_property_owner:
            queryset = queryset.filter(property__owner=self.request.user.propertyowner)
        elif self.request.user.is_tenant:
            queryset = queryset.filter(tenant=self.request.user.tenant)

        # Apply filters from form
        form = InvoiceFilterForm(self.request.GET, user=self.request.user)
        if form.is_valid():
            status = form.cleaned_data.get('status')
            payment_type = form.cleaned_data.get('payment_type')
            date_from = form.cleaned_data.get('date_from')
            date_to = form.cleaned_data.get('date_to')
            property = form.cleaned_data.get('property')
            tenant = form.cleaned_data.get('tenant')

            if status:
                queryset = queryset.filter(status=status)
            if payment_type:
                queryset = queryset.filter(payment_type=payment_type)
            if date_from:
                queryset = queryset.filter(due_date__gte=date_from)
            if date_to:
                queryset = queryset.filter(due_date__lte=date_to)
            if property:
                queryset = queryset.filter(property=property)
            if tenant:
                queryset = queryset.filter(tenant__user__email__icontains=tenant)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = InvoiceFilterForm(self.request.GET, user=self.request.user)
        return context

class InvoiceDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Invoice
    template_name = 'payments/invoice_detail.html'
    context_object_name = 'invoice'

    def test_func(self):
        invoice = self.get_object()
        if self.request.user.is_superuser:
            return True
        elif self.request.user.is_property_owner:
            return invoice.property.owner == self.request.user.propertyowner
        elif self.request.user.is_tenant:
            return invoice.tenant == self.request.user.tenant
        return False

class InvoiceCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = 'payments/invoice_form.html'
    success_url = reverse_lazy('payments:invoice_list')

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_property_owner

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        invoice = form.save(commit=False)
        invoice.property = form.cleaned_data['lease_agreement'].property
        invoice.save()
        
        # Send email notification
        from utils.email_utils import send_invoice_creation_email
        try:
            send_invoice_creation_email(invoice)
        except Exception as e:
            messages.warning(self.request, f'Invoice created but email notification failed: {str(e)}')

        messages.success(self.request, 'Invoice created successfully.')
        return super().form_valid(form)

class InvoiceUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = 'payments/invoice_form.html'
    success_url = reverse_lazy('payments:invoice_list')

    def test_func(self):
        invoice = self.get_object()
        if self.request.user.is_superuser:
            return True
        elif self.request.user.is_property_owner:
            return invoice.property.owner == self.request.user.propertyowner
        return False

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Invoice updated successfully.')
        return super().form_valid(form)

@login_required
def get_lease_details(request):
    """AJAX view to get lease agreement details"""
    lease_id = request.GET.get('lease_id')
    lease = get_object_or_404(LeaseAgreement, id=lease_id)
    
    if request.user.is_property_owner and lease.property.owner != request.user.propertyowner:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    data = {
        'property_unit_id': lease.property_unit.id if lease.property_unit else None,
        'tenant_id': lease.tenant.id if lease.tenant else None,
        'rent_amount': float(lease.rent_amount) if lease.rent_amount else 0,
    }
    return JsonResponse(data)

@login_required
def tenant_make_payment(request, pk):
    invoice = get_object_or_404(Invoice, id=pk)
    
    # Validate permissions
    if not request.user.is_tenant or invoice.tenant.user != request.user:
        messages.error(request, "Unauthorized payment attempt")
        return redirect('properties:invoice_detail', pk=pk)

    try:
        # Ensure Stripe configuration exists
        if not invoice.bank_account or invoice.bank_account.account_type != 'Stripe':
            invoice.bank_account = BankAccount.objects.get(
                property=invoice.property,
                account_type='Stripe',
                status='active'
            )
            invoice.save()

        # Create new Stripe session if needed
        if not invoice.stripe_checkout_id:
            stripe.api_key = settings.STRIPE_SECRET_KEY

            success_url = request.build_absolute_uri(
                reverse('properties:invoice_detail', kwargs={'pk': invoice.pk})
            )
            cancel_url = request.build_absolute_uri(
                reverse('properties:invoice_detail', kwargs={'pk': invoice.pk})
            )

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': int(invoice.total_amount * 100),
                        'product_data': {
                            'name': f'Invoice #{invoice.invoice_number}',
                            'description': invoice.description,
                        },
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={'invoice_id': invoice.id}
            )

            invoice.stripe_checkout_id = session.id
            invoice.stripe_payment_intent_id = session.payment_intent
            invoice.payment_url = session.url
            invoice.save()

        return redirect(invoice.payment_url)

    except Exception as e:
        messages.error(request, f'Payment processing error: {str(e)}')
        logger.error(f'Stripe payment error for invoice {invoice.id}: {str(e)}')
        return redirect('properties:invoice_detail', pk=pk)

@login_required
def payment_success(request, pk):
    """Handle successful payment"""
    invoice = get_object_or_404(Invoice, pk=pk)
    
    if not hasattr(request.user, 'tenant') or request.user.tenant != invoice.tenant:
        return HttpResponseForbidden("You don't have permission to view this page")
    
    try:
        # Verify payment with Stripe
        if invoice.stripe_checkout_id:
            session = stripe.checkout.Session.retrieve(invoice.stripe_checkout_id)
            if session.payment_status == 'paid':
                invoice.mark_as_paid()
                messages.success(request, "Payment successful! Your invoice has been marked as paid.")
            else:
                messages.warning(request, "Payment is still processing. Please check back later.")
        else:
            messages.error(request, "No payment information found for this invoice.")
    
    except Exception as e:
        messages.error(request, f"Error verifying payment: {str(e)}")

        create_notification(
        recipient=invoice.tenant.user,
        notification_type='payment_received',
        title='Payment Successful',
        message=f'Your payment of ${invoice.total_amount} for {invoice.property.name} has been processed successfully.',
        related_object=invoice
    )
    
    # Create notification for property owner
    create_notification(
        recipient=invoice.property.owner.user,
        notification_type='payment_received',
        title='Payment Received',
        message=f'Payment of ${invoice.total_amount} received from {invoice.tenant.user.get_full_name()} for {invoice.property.name}.',
        related_object=invoice
    )
    
    return redirect('payments:invoice_detail', pk=invoice.pk)

@require_POST
@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events"""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
        
        if event.type == 'checkout.session.completed':
            session = event.data.object
            invoice_id = session.metadata.get('invoice_id')
            
            if invoice_id:
                with transaction.atomic():
                    # Update invoice
                    invoice = Invoice.objects.get(id=invoice_id)
                    invoice.stripe_payment_intent_id = session.payment_intent
                    invoice.mark_as_paid()
                    
                    # Create payment record
                    payment = Payment.objects.create(
                        lease_agreement=invoice.lease_agreement,
                        payment_type=invoice.payment_type,
                        amount=invoice.amount,
                        due_date=invoice.due_date,
                        payment_date=timezone.now(),
                        status='completed',
                        payment_method='stripe',
                        transaction_id=session.payment_intent,
                        stripe_payment_intent_id=session.payment_intent,
                        stripe_payment_method_id=session.payment_method,
                        paid_by=invoice.tenant.user
                    )
        
        return JsonResponse({'status': 'success'})
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
def confirm_cash_payment(request, lease_agreement_id):
    """Handle cash payment confirmation"""
    lease_agreement = get_object_or_404(LeaseAgreement, id=lease_agreement_id)
    
    if request.method == 'POST':
        form = PaymentConfirmationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Create payment record
                payment = Payment.objects.create(
                    lease_agreement=lease_agreement,
                    payment_type=request.POST.get('payment_type', 'rent'),
                    amount=Decimal(request.POST.get('amount')),
                    due_date=timezone.now().date(),
                    payment_date=timezone.now(),
                    status='completed',
                    payment_method='cash',
                    transaction_id=f'CASH-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                    paid_by=request.user
                )
                
                # Create payment history
                PaymentHistory.objects.create(
                    payment=payment,
                    user=request.user,
                    action='COMPLETED',
                    description=f'Cash payment of {payment.amount} received'
                )
                
                messages.success(request, 'Cash payment has been recorded successfully.')
                return redirect('payments:payment_detail', pk=payment.pk)
    else:
        form = PaymentConfirmationForm()
    
    return render(request, 'payments/confirm_cash_payment.html', {
        'form': form,
        'lease_agreement': lease_agreement
    })

@login_required
def confirm_bank_transfer(request, lease_agreement_id):
    """Handle bank transfer confirmation"""
    lease_agreement = get_object_or_404(LeaseAgreement, id=lease_agreement_id)
    
    if request.method == 'POST':
        form = PaymentConfirmationForm(request.POST)
        if form.is_valid():
            reference_number = request.POST.get('reference_number')
            with transaction.atomic():
                # Create payment record
                payment = Payment.objects.create(
                    lease_agreement=lease_agreement,
                    payment_type=request.POST.get('payment_type', 'rent'),
                    amount=Decimal(request.POST.get('amount')),
                    due_date=timezone.now().date(),
                    payment_date=timezone.now(),
                    status='completed',
                    payment_method='bank_transfer',
                    transaction_id=reference_number,
                    paid_by=request.user
                )
                
                # Create payment history
                PaymentHistory.objects.create(
                    payment=payment,
                    user=request.user,
                    action='COMPLETED',
                    description=f'Bank transfer payment of {payment.amount} received. Ref: {reference_number}'
                )
                
                messages.success(request, 'Bank transfer has been recorded successfully.')
                return redirect('payments:payment_detail', pk=payment.pk)
    else:
        form = PaymentConfirmationForm()
    
    return render(request, 'payments/confirm_bank_transfer.html', {
        'form': form,
        'lease_agreement': lease_agreement
    })

@login_required
def create_security_deposit_payment(request, lease_agreement_id):
    """Create security deposit payment record"""
    lease_agreement = get_object_or_404(LeaseAgreement, id=lease_agreement_id)
    
    if request.method == 'POST':
        form = PaymentForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                # Create payment record
                payment = Payment.objects.create(
                    lease_agreement=lease_agreement,
                    payment_type='security_deposit',
                    amount=form.cleaned_data['amount'],
                    due_date=form.cleaned_data['due_date'],
                    payment_date=timezone.now(),
                    status='pending',
                    payment_method='pending',
                    paid_by=lease_agreement.tenant.user
                )
                
                # Create payment history
                PaymentHistory.objects.create(
                    payment=payment,
                    user=request.user,
                    action='CREATED',
                    description=f'Security deposit payment of {payment.amount} created'
                )
                
                messages.success(request, 'Security deposit payment has been created successfully.')
                return redirect('payments:payment_detail', pk=payment.pk)
    else:
        initial_data = {
            'lease_agreement': lease_agreement,
            'payment_type': 'security_deposit',
            'amount': lease_agreement.security_deposit_amount,
            'due_date': timezone.now().date()
        }
        form = PaymentForm(user=request.user, initial=initial_data)
    
    return render(request, 'payments/security_deposit_form.html', {
        'form': form,
        'lease_agreement': lease_agreement
    })
