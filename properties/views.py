from django.shortcuts import render, redirect, get_object_or_404
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.db.models import Avg
from datetime import datetime, timedelta
from .models import Property, LeaseAgreement,TenantProperty
from decimal import Decimal
import json
from django.db.models.functions import TruncMonth
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from datetime import date
from django.db.models import Avg, Sum
from .utils import check_property_limit
from django.conf import settings
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string
import pdfkit
import json
import logging
import stripe
from properties.utils import (
    send_maintenance_request_notification,
    send_invoice_notification,
    send_lease_notification
)
from .utils import check_unit_limit
from datetime import datetime, timedelta
from notifications.utils import create_notification
from .models import Property, PropertyUnit, LeaseAgreement, BankAccount, PropertyMaintenance,PropertyImage,PropertyManager
from accounts.models import Tenant, PropertyOwner
from payments.models import Invoice
from accounts.forms import CustomUserCreationForm
from properties.utils import save_property_with_limit_check
logger = logging.getLogger(__name__)

from django.forms import inlineformset_factory
from django.db.models import Q
from django.core.paginator import Paginator
from .forms import (
    PropertyForm, PropertyImageForm, LeaseAgreementForm,
    PropertyMaintenanceForm, PropertySearchForm, PropertyUnitForm, BankAccountForm, CommercialUnitForm
)
from accounts.models import PropertyOwner, Tenant
from django.db import transaction
from payments.models import Invoice
from payments.forms import InvoiceForm



UnitFormSet = inlineformset_factory(
    Property,
    PropertyUnit,
    form=PropertyUnitForm,
    fields=['unit_number', 'monthly_rent',
           'bedrooms', 'bathrooms', 'square_feet', 'is_available'],
    extra=1,
    can_delete=True
)


@login_required
def property_list(request):
    form = PropertySearchForm(request.GET)

    # Filter properties based on user role
    if request.user.is_property_owner():
        properties = Property.objects.filter(owner__user=request.user)
    else:
        properties = Property.objects.all()

    if form.is_valid():
        keyword = form.cleaned_data.get('keyword')
        property_type = form.cleaned_data.get('property_type')
        city = form.cleaned_data.get('city')
        price_range = form.cleaned_data.get('price_range')
        bedrooms = form.cleaned_data.get('bedrooms')

        if keyword:
            properties = properties.filter(
                Q(title__icontains=keyword) |
                Q(description__icontains=keyword) |
                Q(address__icontains=keyword)
            )
        if property_type:
            properties = properties.filter(property_type=property_type)
        if city:
            properties = properties.filter(city__icontains=city)
        if price_range:
            min_price, max_price = map(int, price_range.split('-'))
            properties = properties.filter(monthly_rent__range=(min_price, max_price))
        if bedrooms:
            if bedrooms == '6+':
                properties = properties.filter(bedrooms__gte=6)
            else:
                properties = properties.filter(bedrooms=int(bedrooms))

    return render(request, 'properties/property_list.html', {
        'properties': properties,
        'form': form
    })



@login_required
def property_detail(request, pk):
    property = get_object_or_404(Property, pk=pk)
    if request.user != property.owner.user:
        return HttpResponseForbidden()

    lease_form = LeaseAgreementForm(property=property)
    bank_form = BankAccountForm(property=property)

    # Handle POST actions
    if request.method == 'POST':
        if 'create_lease' in request.POST:
            lease_form = LeaseAgreementForm(request.POST, request.FILES, property=property)
            if lease_form.is_valid():
                lease = lease_form.save(commit=False)
                lease.property = property
                lease.status = 'pending'
                lease.save()
                messages.success(request, 'Lease agreement created successfully!')
                return redirect('properties:property_detail', pk=pk)

        elif 'create_bank_account' in request.POST:
            bank_form = BankAccountForm(request.POST, property=property)
            if bank_form.is_valid():
                account = bank_form.save(commit=False)
                account.property = property
                account.save()
                messages.success(request, 'Payment account added successfully!')
                return redirect('properties:property_detail', pk=pk)

        elif 'upload_images' in request.POST and request.FILES.getlist('images'):
            images = request.FILES.getlist('images')
            for img in images:
                PropertyImage.objects.create(property=property, image=img)
            messages.success(request, f'{len(images)} image(s) uploaded successfully.')
            return redirect('properties:property_detail', pk=pk)

    # Property unit stats
    property_units = PropertyUnit.objects.filter(property=property).prefetch_related(
        'lease_agreements',
        'maintenance_requests'
    )
    total_units = property_units.count()
    available_units = property_units.filter(is_available=True).count()
    occupied_units = property_units.filter(is_available=False).count()
    #unit_occupied = property_units.filter(status='Occupied')

    # Tenant and lease stats
    tenant_count = property.leaseagreement_set.filter(status='active').values('tenant').distinct().count()
    lease_count = property.leaseagreement_set.filter(status='active').count()
    active_lease = property.leaseagreement_set.filter(status='active')

    # Bank accounts
    active_accounts = property.bank_accounts.filter(status='Active')
    account_count = active_accounts.count()

    # Maintenance and invoices
    maintenance_requests = PropertyMaintenance.objects.filter(property=property)
    invoices = property.property_invoices.all().order_by('-issue_date')

    # Add active lease and all leases to units
    for unit in property_units:
        unit.active_lease = unit.lease_agreements.filter(status='active').first()
        unit.all_leases = unit.lease_agreements.select_related(
            'tenant__user',
            'property_unit'
        ).order_by('-created_at')

    context = {
        'property': property,
        'lease_form': lease_form,
        'bank_form': bank_form,
        'unit_form': PropertyUnitForm(),
        'has_active_accounts': active_accounts.exists(),
        'maintenance_requests': maintenance_requests,
        'property_units': property_units,
        'total_units': total_units,
        'available_units': available_units,
        'occupied_units': occupied_units,
        'active_lease': active_lease,
        'invoices': invoices,
    }
    return render(request, 'properties/property_detail.html', context)

@login_required
def property_create(request):
    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # First create the property object without saving
                    property = form.save(commit=False)
                    property.owner = request.user.propertyowner

                    # Use the new utility function to save with limit check
                    if save_property_with_limit_check(property, request):
                        # Handle image uploads
                        for image in request.FILES.getlist('images'):
                            PropertyImage.objects.create(
                                property=property,
                                image=image
                            )
                        messages.success(request, 'Property created successfully!')
                        return redirect('properties:property_detail', pk=property.pk)
                    return redirect('properties:property_list')
            except Exception as e:
                messages.error(request, f'Error creating property: {str(e)}')
                return redirect('properties:property_list')
    else:
        form = PropertyForm()

    return render(request, 'properties/property_form.html', {'form': form})

@login_required
def property_unit(request, property_pk):
    property = get_object_or_404(Property, property_pk)
    if request.method == 'POST':
        form = Property_unit(request.POST)

        if form.is_valid():
            property = form.save(commit=False)
            property.owner = PropertyOwner.objects.get(user=request.user)
            property.save()


            messages.success(request, 'Property listed successfully!')

            return redirect('properties:property_detail', pk = property.pk)
    else:
        form = PropertyForm()
    return render(request, 'properties/property_unit.html', {'property': property})

@login_required
def lease_agreement_create(request, property_pk):
    property = get_object_or_404(Property, pk=property_pk)

    # Check if user is the property owner
    if not request.user.is_property_owner() or property.owner.user != request.user:
        messages.error(request, "You don't have permission to create lease agreements for this property.")
        return redirect('properties:property_detail', pk=property_pk)

    if request.method == 'POST':
        form = LeaseAgreementForm(request.POST, property=property)
        if form.is_valid():
            lease = form.save(commit=False)
            lease.property = property

            # Validate dates
            if lease.start_date >= lease.end_date:
                form.add_error('end_date', 'End date must be after start date')
            else:
                # Check for overlapping leases
                overlapping = LeaseAgreement.objects.filter(
                    property_unit=lease.property_unit,
                    status='active'
                ).filter(
                    Q(start_date__range=(lease.start_date, lease.end_date)) |
                    Q(end_date__range=(lease.start_date, lease.end_date))
                ).exists()

                if overlapping:
                    form.add_error('property_unit', 'This unit is already leased during this period')
                else:
                    lease.save()

                    # Send email notification
                    try:
                        send_lease_notification(lease, request)
                    except Exception as e:
                        messages.warning(request, f'Lease created but email notification failed: {str(e)}')

                    # Create notification for tenant
                    create_notification(
                        recipient=lease.tenant.user,
                        title='New Lease Agreement',
                        message=f'A new lease agreement has been created for {property.title}',
                        notification_type='lease_created'
                    )

                    messages.success(request, 'Lease agreement created successfully.')
                    return redirect('properties:property_detail', pk=property.pk)
    else:
        form = LeaseAgreementForm(property=property)

    return render(request, 'properties/lease_form.html', {
        'form': form,
        'property': property,
        'action': 'Create'
    })

@login_required
def select_lease_for_invoice(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)

    if request.user != property_obj.owner.user:
        return HttpResponseForbidden("You don't have permission to access this property.")

    active_leases = LeaseAgreement.objects.filter(
        property=property_obj, status='active'
    ).select_related('tenant', 'property_unit')

    if request.method == 'POST':
        lease_id = request.POST.get('lease_id')
        if lease_id:
            return redirect('properties:invoice_create', lease_id=lease_id)

    if not active_leases.exists():
        messages.warning(request, "No active lease agreements found for this property.")
        return redirect('properties:property_detail', pk=property_id)

    if active_leases.count() == 1:
        return redirect('properties:invoice_create', lease_id=active_leases.first().id)

    return render(request, 'properties/select_lease_for_invoice.html', {
        'property': property_obj,
        'active_leases': active_leases,
    })


@login_required
def lease_agreement_update(request, pk):
    lease = get_object_or_404(LeaseAgreement, pk=pk)

    # Check if user is the property owner
    if not request.user.is_property_owner() or lease.property.owner.user != request.user:
        messages.error(request, "You don't have permission to update this lease agreement.")
        return redirect('properties:lease_detail', pk=pk)

    if request.method == 'POST':
        form = LeaseAgreementForm(request.POST, instance=lease, property=lease.property)
        if form.is_valid():
            lease = form.save(commit=False)

            # Validate dates
            if lease.start_date >= lease.end_date:
                form.add_error('end_date', 'End date must be after start date')
            else:
                # Check for overlapping leases (excluding current lease)
                overlapping = LeaseAgreement.objects.filter(
                    property_unit=lease.property_unit,
                    status='active'
                ).exclude(pk=lease.pk).filter(
                    Q(start_date__range=(lease.start_date, lease.end_date)) |
                    Q(end_date__range=(lease.start_date, lease.end_date))
                ).exists()

                if overlapping:
                    form.add_error('property_unit', 'This unit is already leased during this period')
                else:
                    lease.save()

                    # Create notification for tenant
                    create_notification(
                        recipient=lease.tenant.user,
                        notification_type='lease_update',
                        title='Lease Agreement Updated',
                        message=f'Your lease agreement for {lease.property.title} has been updated',
                        related_object=lease
                    )

                    messages.success(request, 'Lease agreement updated successfully.')
                    return redirect('properties:lease_detail', pk=pk)
    else:
        form = LeaseAgreementForm(instance=lease, property=lease.property)

    return render(request, 'properties/lease_form.html', {
        'form': form,
        'lease': lease,
        'action': 'Update'
    })

from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from properties.models import Property, LeaseAgreement

@login_required
def lease_agreement_delete(request, property_pk, pk):
    property = get_object_or_404(Property, pk=property_pk)
    lease = get_object_or_404(LeaseAgreement, pk=pk, property=property)

    # Check if user is the property owner
    if not request.user.is_property_owner() or property.owner.user != request.user:
        messages.error(request, "You don't have permission to delete this lease agreement.")
        return redirect('properties:lease_detail', pk=pk)

    if request.method == 'POST':
        # Optionally, notify the tenant here
        lease.delete()
        messages.success(request, 'Lease agreement deleted successfully.')
        return redirect('properties:property_detail', pk=property_pk)

    return render(request, 'properties/lease_delete_confirm.html', {
        'lease': lease
    })

@login_required
def maintenance_request_select_unit(request):
    if not request.user.is_tenant():
        messages.error(request, 'Only tenants can submit maintenance requests.')
        return redirect('accounts:dashboard')

    leases = LeaseAgreement.objects.select_related('property_unit', 'property').filter(
        tenant__user=request.user,
        status='active'
    )

    if not leases.exists():
        messages.error(request, 'No active lease agreements found.')
        return redirect('accounts:dashboard')

    # If only one lease, redirect directly to create form
    if leases.count() == 1:
        lease = leases.first()
        if lease.property_unit and lease.property_unit.id:
            return redirect('properties:maintenance_request_create', unit_pk=lease.property_unit.id)
        else:
            messages.error(request, 'No valid unit found for your lease.')
            return redirect('properties:maintenance_request_list')

    # If multiple leases, show selection form
    return render(request, 'properties/maintenance_property_select.html', {
        'leases': leases
    })

@login_required
def maintenance_request_create(request, unit_pk):
    unit = get_object_or_404(PropertyUnit, pk=unit_pk)
    property = unit.property

    if request.method == 'POST':
        form = PropertyMaintenanceForm(request.POST, request.FILES)
        if form.is_valid():
            maintenance = form.save(commit=False)
            maintenance.property = property
            maintenance.property_unit = unit
            maintenance.reported_by = request.user
            maintenance.save()

            # Send notifications using the updated function
            if send_maintenance_request_notification(maintenance, request):
                messages.success(request, 'Maintenance request created and notifications sent successfully!')
            else:
                messages.warning(request, 'Maintenance request created but there was an issue sending notifications.')

            return redirect('properties:maintenance_request_list')
    else:
        form = PropertyMaintenanceForm()

    return render(request, 'properties/maintenance_form.html', {
        'form': form,
        'unit': unit,
        'property': property
    })

@login_required
def maintenance_request_list(request):
    if request.user.is_property_owner():
        maintenance_requests = PropertyMaintenance.objects.filter(
            property__owner__user=request.user
        ).order_by('-reported_date')
    elif request.user.is_tenant():
        maintenance_requests = PropertyMaintenance.objects.filter(
            reported_by=request.user
        ).order_by('-reported_date')
    else:
        maintenance_requests = PropertyMaintenance.objects.all().order_by('-reported_date')

    return render(request, 'properties/maintenance_list.html', {
        'maintenance_requests': maintenance_requests
    })
@login_required
def lease_list(request):
    if request.user.is_property_owner():
        leases = LeaseAgreement.objects.filter(
            property__owner__user=request.user
        ).order_by('-start_date')
    elif request.user.is_tenant():
        leases = LeaseAgreement.objects.filter(
            tenant__user=request.user
        ).order_by('-start_date')
    else:
        leases = LeaseAgreement.objects.all().order_by('-start_date')

    return render(request, 'properties/lease_list.html', {
        'leases': leases
    })

@login_required
def unit_create(request, property_pk):
    property = get_object_or_404(Property, pk=property_pk)

    # Check if user is the property owner
    if not request.user.is_property_owner() or property.owner.user != request.user:
        messages.error(request, "You don't have permission to add units to this property.")
        return redirect('properties:property_detail', pk=property_pk)

    # Select form based on property type
    is_commercial = property.property_type.lower() == 'commercial'
    FormClass = CommercialUnitForm if is_commercial else PropertyUnitForm

    if request.method == 'POST':
        form = FormClass(request.POST, property_instance=property)
        if form.is_valid():
            try:
                # Check unit limit before saving
                if check_unit_limit(property, request):
                    unit = form.save(commit=False)
                    unit.property = property

                    # Set bedrooms and bathrooms to 0 for commercial units
                    if is_commercial:
                        unit.bedrooms = 0
                        unit.bathrooms = 0

                    unit.save()
                    messages.success(request, 'Property unit created successfully.')
                    return redirect('properties:property_detail', pk=property_pk)
                return redirect('properties:property_detail', pk=property_pk)
            except Exception as e:
                messages.error(request, f'Error creating unit: {str(e)}')
                return redirect('properties:property_detail', pk=property_pk)
    else:
        form = FormClass(property_instance=property)

    return render(request, 'properties/unit_form.html', {
        'form': form,
        'property': property,
        'action': 'Create',
        'is_commercial': is_commercial
    })

@login_required
def unit_update(request, unit_pk):
    unit = get_object_or_404(PropertyUnit, pk=unit_pk)

    # Check if user is the property owner
    if not request.user.is_property_owner() or unit.property.owner.user != request.user:
        messages.error(request, "You don't have permission to update this unit.")
        return redirect('properties:property_detail', pk=unit.property.pk)

    # Select form based on property type
    is_commercial = unit.property.property_type.lower() == 'commercial'
    FormClass = CommercialUnitForm if is_commercial else PropertyUnitForm

    if request.method == 'POST':
        form = FormClass(request.POST, instance=unit, property_instance=unit.property)
        if form.is_valid():
            form.save()
            messages.success(request, 'Unit updated successfully!')
            return redirect('properties:property_detail', pk=unit.property.pk)
    else:
        form = FormClass(instance=unit, property_instance=unit.property)

    return render(request, 'properties/unit_form.html', {
        'form': form,
        'property': unit.property,
        'action': 'Update',
        'is_commercial': is_commercial
    })

@login_required
def unit_delete(request, unit_pk):
    unit = get_object_or_404(PropertyUnit, pk=unit_pk)
    property = unit.property

    # Check if user is the property owner
    if not request.user.is_property_owner or property.owner.user != request.user:
        messages.error(request, 'You do not have permission to delete this unit.')
        return redirect('properties:property_detail', pk=property.id)

    try:
        unit.delete()
        messages.success(request, 'Property unit deleted successfully.')
    except Exception as e:
        messages.error(request, f'Error deleting unit: {str(e)}')

    return redirect('properties:property_detail', pk=property.id)

@login_required
def bank_account_create(request, property_pk):
    property = get_object_or_404(Property, pk=property_pk)

    if request.method == 'POST':
        form = BankAccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.property = property
            account.created_by = request.user
            account.save()
            messages.success(request, 'Payment account created successfully!')
            return redirect('properties:property_detail', pk=property.pk)
    else:
        form = BankAccountForm(initial={'property': property})

    return render(request, 'properties/bank_account_form.html', {
        'form': form,
        'property': property
    })


@login_required
def bank_account_delete(request, property_pk, account_pk):
    bank_account = get_object_or_404(BankAccount, pk=account_pk, property_id=property_pk)

    # Check if user is the property owner
    if request.user != bank_account.property.owner.user:
        return HttpResponseForbidden("Only the property owner can delete this bank account.")

    # Check if bank account is in use by any active lease
    in_use = LeaseAgreement.objects.filter(bank_account=bank_account, end_date__gte=timezone.now()).exists()
    if in_use:
        messages.error(request, 'Cannot delete this bank account as it is linked to active lease agreements.')
        return redirect('properties:property_detail', pk=property_pk)

    if request.method == 'POST':
        bank_account.delete()
        messages.success(request, 'Bank account deleted successfully.')
        return redirect('properties:property_detail', pk=property_pk)

    return render(request, 'properties/bank_account_delete_confirm.html', {
        'bank_account': bank_account,
        'property': bank_account.property
    })

@login_required
def bank_account_edit(request, property_pk, pk):
    property = get_object_or_404(Property, pk=property_pk)

    # Check ownership
    if request.user != property.owner.user:
        return HttpResponseForbidden()

    account = get_object_or_404(BankAccount, pk=pk, property=property)

    if request.method == 'POST':
        form = BankAccountForm(request.POST, instance=account, property=property)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bank account updated successfully.')
            return redirect('properties:property_detail', pk=property.pk)
    else:
        form = BankAccountForm(instance=account, property=property)

    return render(request, 'properties/bank_account_form.html', {
        'form': form,
        'property': property,
        'account': account,
    })


@login_required
def lease_status_change(request, property_pk, pk):
    """Change lease agreement status"""
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Method not allowed'}, status=405)

        property = get_object_or_404(Property, pk=property_pk)
        lease = get_object_or_404(LeaseAgreement, pk=pk, property=property)

        if not request.user.is_property_owner() or request.user != property.owner.user:
            return JsonResponse({'error': 'Unauthorized'}, status=403)

        data = json.loads(request.body)
        new_status = data.get('status')

        if new_status not in dict(LeaseAgreement.STATUS_CHOICES):
            return JsonResponse({'error': 'Invalid status'}, status=400)

        # Check if the status change is valid
        if lease.status == 'active' and new_status == 'pending':
            return JsonResponse({'error': 'Cannot change active lease to pending'}, status=400)

        lease.status = new_status
        lease.save()

        # Create notification for tenant
        create_notification(
            recipient=lease.tenant.user,
            notification_type='lease_update',
            title='Lease Agreement Status Updated',
            message=f'The status of your lease agreement for {property.title} has been updated to {new_status}.',
            related_object=lease
        )

        # Create notification for property owner
        create_notification(
            recipient=property.owner.user,
            notification_type='lease_update',
            title='Lease Agreement Status Updated',
            message=f'The status of the lease agreement for {lease.tenant.user.get_full_name()} at {property.title} has been updated to {new_status}.',
            related_object=lease
        )

        return JsonResponse({'status': 'success'})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def tenant_make_payment(request, pk):
    try:
        # Get the invoice first
        invoice = get_object_or_404(Invoice, id=pk)

        # Validate permissions
        if not request.user.is_tenant or invoice.tenant.user != request.user:
            messages.error(request, "Unauthorized payment attempt")
            return redirect('properties:invoice_detail', pk=pk)

        # Get bank account and validate Stripe configuration
        if not invoice.bank_account or not invoice.bank_account.secret_key:
            messages.error(request, "Payment system is not properly configured for this invoice")
            return redirect('properties:invoice_detail', pk=pk)

        # Use the bank account's Stripe secret key
        stripe.api_key = invoice.bank_account.secret_key

        # Create Stripe session
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card', 'us_bank_account'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': int(invoice.total_amount * 100),
                        'product_data': {
                            'name': f'Invoice #{invoice.invoice_number}',
                            'description': invoice.description or 'Payment for rental services',
                        },
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=request.build_absolute_uri(
                    reverse('properties:payment_success', kwargs={'pk': invoice.id})
                ),
                cancel_url=request.build_absolute_uri(
                    reverse('properties:invoice_detail', kwargs={'pk': invoice.id})
                ),
                metadata={'invoice_id': invoice.id}
            )

            # Update invoice with Stripe session info
            invoice.stripe_checkout_id = session.id
            invoice.stripe_payment_intent_id = session.payment_intent
            invoice.save()

            # Redirect to Stripe checkout
            return redirect(session.url)

        except stripe.error.StripeError as e:
            logger.error(f'Stripe payment error for invoice {invoice.id}: {str(e)}')
            messages.error(request, f"Payment processing error: {str(e)}")
            return redirect('properties:invoice_detail', pk=pk)

    except Exception as e:
        logger.error(f'Error processing payment: {str(e)}')
        messages.error(request, "An error occurred processing your payment")
        return redirect('properties:invoice_detail', pk=pk)

@login_required
def payment_success(request, pk):
    invoice = get_object_or_404(Invoice, id=pk)

    if not request.user.is_tenant or invoice.tenant.user != request.user:
        messages.error(request, "You don't have permission to view this payment.")
        return redirect('properties:invoice_detail', pk=pk)

    # Verify payment status with Stripe
    import stripe
    from django.conf import settings

    # Use the bank account's Stripe secret key
    stripe.api_key = invoice.bank_account.secret_key

    try:
        session = stripe.checkout.Session.retrieve(invoice.stripe_checkout_id)
        if session.payment_status == 'paid':
            # Mark invoice as paid if not already
            if invoice.status != 'paid':
                invoice.stripe_payment_intent_id = session.payment_intent
                owner_invoice = invoice.mark_as_paid()
                messages.success(request, 'Payment successful! Invoice has been marked as paid.')
            else:
                messages.info(request, 'Invoice was already marked as paid.')
        else:
            messages.warning(request, 'Payment is still pending. Please contact support if you think this is an error.')
    except Exception as e:
        messages.error(request, f'Error verifying payment: {str(e)}')

    return redirect('properties:invoice_detail', pk=pk)


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
def mark_invoice_as_paid(request, pk):
    invoice = get_object_or_404(Invoice, id=pk)

    # Only property owner can mark as paid
    if not request.user.is_property_owner or invoice.property.owner.user != request.user:
        messages.error(request, "You don't have permission to update this invoice.")
        return redirect('properties:invoice_detail', pk=invoice.id)

    try:
        # Mark invoice as paid and create owner invoice
        owner_invoice = invoice.mark_as_paid()
        messages.success(request, 'Invoice marked as paid and owner invoice created.')
        return redirect('properties:invoice_detail', pk=owner_invoice.id)
    except Exception as e:
        messages.error(request, f'Error marking invoice as paid: {str(e)}')
        return redirect('properties:invoice_detail', pk=invoice.id)

@login_required
def lease_delete(request, property_pk, lease_pk):
    lease = get_object_or_404(LeaseAgreement, pk=lease_pk, property_id=property_pk)

    # Check if user is property owner
    if request.user != lease.property.owner.user:
        return HttpResponseForbidden("Only property owner can delete lease agreements.")

    if request.method == 'POST':
        # Store the unit for redirection
        property_id = lease.property.id
        # Delete the lease
        lease.delete()
        messages.success(request, 'Lease agreement deleted successfully.')
        return redirect('properties:property_detail', pk=property_id)

    return render(request, 'properties/lease_delete_confirm.html', {
        'lease': lease
    })

@login_required
def invoice_list(request):
    """List all invoices for the current user"""
    if request.user.is_property_owner:
        invoices = Invoice.objects.filter(property__owner=request.user.propertyowner)
    elif request.user.is_tenant:
        invoices = Invoice.objects.filter(tenant=request.user.tenant)
    else:
        invoices = Invoice.objects.all()

    paginator = Paginator(invoices.order_by('-created_at'), 10)
    page = request.GET.get('page')
    invoices = paginator.get_page(page)

    return render(request, 'payments/invoice_list.html', {
        'invoices': invoices
    })

@login_required
def invoice_detail(request, pk):
    """View invoice details"""
    invoice = get_object_or_404(Invoice, pk=pk)
    property_address = invoice.property.address

    # Check permissions

    return render(request, 'properties/invoice_detail.html', {
        'invoice': invoice,
        'property_address':property_address
    })

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO

@login_required
def download_invoice(request, pk):
    """Download invoice as PDF"""
    invoice = get_object_or_404(Invoice, pk=pk)

    # Check permissions - only property owner can download
    if not request.user.is_property_owner or invoice.property.owner.user != request.user:
        messages.error(request, "Only property owners can download invoices.")
        return redirect('accounts:dashboard')

    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # Header
    elements.append(Paragraph(f"INVOICE #{invoice.invoice_number}", styles['Heading1']))
    elements.append(Spacer(1, 20))

    # Company Info
    elements.append(Paragraph("Rental Management System", styles['Heading2']))
    elements.append(Spacer(1, 20))

    # Invoice Details
    data = [
        ["Issue Date:", invoice.issue_date.strftime("%B %d, %Y")],
        ["Due Date:", invoice.due_date.strftime("%B %d, %Y")],
        ["Status:", invoice.status.title()],
        ["Property:", invoice.property.title],
        ["Unit:", invoice.lease_agreement.property_unit.unit_number],
        ["Tenant:", invoice.tenant.user.get_full_name()],
    ]

    table = Table(data, colWidths=[2*inch, 4*inch])
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))

    # Amount Details
    amount_data = [
        ["Description", "Amount"],
        ["Amount", f"₹{invoice.amount}"],
    ]
    if invoice.late_fee > 0:
        amount_data.append(["Late Fee", f"₹{invoice.late_fee}"])
    amount_data.append(["Total Amount", f"₹{invoice.total_amount}"])

    amount_table = Table(amount_data, colWidths=[3*inch, 3*inch])
    amount_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ]))
    elements.append(amount_table)

    # Build PDF
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    # Create response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{invoice.invoice_number}.pdf"'
    response.write(pdf)

    return response

@login_required
def download_lease(request, pk):
    """Download lease agreement as PDF"""
    lease = get_object_or_404(LeaseAgreement, pk=pk)

    # Check permissions - only property owner can download
    if not request.user.is_property_owner or lease.property.owner.user != request.user:
        messages.error(request, "Only property owners can download lease agreements.")
        return redirect('accounts:dashboard')

    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # Header
    elements.append(Paragraph("LEASE AGREEMENT", styles['Heading1']))
    elements.append(Spacer(1, 20))

    # Property Details
    elements.append(Paragraph("Property Information", styles['Heading2']))
    property_data = [
        ["Property Name:", lease.property.title],
        ["Address:", lease.property.address],
        ["Unit:", lease.property_unit.unit_number],
    ]

    property_table = Table(property_data, colWidths=[2*inch, 4*inch])
    property_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(property_table)
    elements.append(Spacer(1, 20))

    # Lease Terms
    elements.append(Paragraph("Lease Terms", styles['Heading2']))
    terms_data = [
        ["Start Date:", lease.start_date.strftime("%B %d, %Y")],
        ["End Date:", lease.end_date.strftime("%B %d, %Y")],
        ["Monthly Rent:", f"₹{lease.monthly_rent}"],
        ["Security Deposit:", f"₹{lease.security_deposit}"],
    ]

    terms_table = Table(terms_data, colWidths=[2*inch, 4*inch])
    terms_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(terms_table)
    elements.append(Spacer(1, 20))

    # Signatures
    elements.append(Paragraph("Signatures", styles['Heading2']))
    elements.append(Spacer(1, 40))

    sig_data = [
        ["_________________________", "_________________________"],
        ["Property Owner", "Tenant"],
        [lease.property.owner.user.get_full_name(), lease.tenant.user.get_full_name()],
        ["Date: ________________", "Date: ________________"],
    ]

    sig_table = Table(sig_data, colWidths=[3*inch, 3*inch])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(sig_table)

    # Build PDF
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    # Create response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="lease_agreement_{lease.id}.pdf"'
    response.write(pdf)

    return response

from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from payments.forms import InvoiceForm
from properties.utils import send_invoice_notification  # if you're using this
from properties.models import LeaseAgreement

@login_required
def invoice_create(request, lease_id):
    lease = get_object_or_404(LeaseAgreement, id=lease_id)
    property = lease.property

    if request.user != property.owner.user:
        messages.error(request, "You don't have permission to create invoices for this property.")
        return redirect('properties:lease_detail', pk=lease_id)

    if request.method == 'POST':
        form = InvoiceForm(request.POST, user=request.user, lease=lease)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.property = property
            invoice.tenant = lease.tenant
            invoice.lease_agreement = lease
            invoice.save()
            messages.success(request, 'Invoice created successfully.')
            return redirect('properties:invoice_detail', pk=invoice.pk)
    else:
        initial_data = {
            'amount': lease.monthly_rent,
            'due_date': date.today() + timedelta(days=30)
        }
        form = InvoiceForm(initial=initial_data, user=request.user, lease=lease)

    return render(request, 'payments/invoice_form.html', {
        'form': form,
        'lease': lease,
        'property': property
    })


@login_required
def invoice_update(request, pk):
    """Update an existing invoice"""
    invoice = get_object_or_404(Invoice, pk=pk)

    # Check permissions
    if not request.user.is_superuser and not request.user.is_property_owner:
        return HttpResponseForbidden("You don't have permission to update invoices")

    if request.user.is_property_owner and invoice.property.owner != request.user.propertyowner:
        return HttpResponseForbidden("You don't have permission to update this invoice")

    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        if form.is_valid():
            form.save()
            messages.success(request, 'Invoice updated successfully.')
            return redirect('properties:invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice)

    return render(request, 'properties/invoice_form.html', {
        'form': form,
        'invoice': invoice,
        'title': 'Update Invoice'
    })
@login_required
def lease_detail(request, pk=None):
    # Ensure user is a tenant or property owner
    if not request.user.is_tenant() and not request.user.is_property_owner():
        messages.error(request, 'Only tenants and property owners can access lease details.')
        return redirect('accounts:dashboard')

    # If pk is provided, get specific lease
    if pk:
        lease = get_object_or_404(LeaseAgreement, pk=pk)
        # Ensure user has permission to view this lease
        if not (
            (request.user.is_tenant() and lease.tenant.user == request.user) or
            (request.user.is_property_owner() and lease.property.owner.user == request.user)
        ):
            messages.error(request, "You don't have permission to view this lease.")
            return redirect('accounts:dashboard')
        return render(request, 'properties/lease_detail.html', {'lease': lease})

    # If no pk, get all leases for the current user
    if request.user.is_tenant():
        leases = LeaseAgreement.objects.filter(tenant__user=request.user).order_by('-start_date')
    else:  # property owner
        leases = LeaseAgreement.objects.filter(property__owner__user=request.user).order_by('-start_date')

    if not leases.exists():
        messages.error(request, 'No lease agreements found.')
        return redirect('accounts:dashboard')

    return render(request, 'properties/lease_detail.html', {
        'leases': leases
    })

@login_required
def get_lease_details(request, lease_id):
    # Ensure user is a tenant or property owner
    if not request.user.is_tenant() and not request.user.is_property_owner():
        messages.error(request, 'Only tenants or property owners can access lease details.')
        return redirect('accounts:dashboard')

    # Get the lease agreement by ID
    lease = get_object_or_404(LeaseAgreement, id=lease_id)

    # Check if user has permission to view this lease
    if not (request.user == lease.tenant.user or request.user == lease.property.owner.user):
        messages.error(request, 'You don\'t have permission to view this lease.')
        return redirect('properties:lease_list')

    return render(request, 'properties/get_lease_detail.html', {
        'lease': lease
    })

@login_required
def maintenance_request_detail(request, pk):
    maintenance = get_object_or_404(PropertyMaintenance, pk=pk)

    # Check if user has permission to view this maintenance request
    if request.user.is_superuser:
        return HttpResponseForbidden("You don't have permission to view this maintenance request.")

    return render(request, 'properties/maintenance_request_detail.html', {
        'maintenance': maintenance
    })

@login_required
def maintenance_request_change_status(request, pk):
    maintenance = get_object_or_404(PropertyMaintenance, pk=pk)

    # Check if user has permission to change status
    has_permission = (
        request.user.is_superuser or
        request.user == maintenance.property.owner.user or
        (hasattr(request.user, 'propertymanager') and
         maintenance.property in request.user.propertymanager.assigned_properties.all())
    )

    if not has_permission:
        messages.error(request, "You don't have permission to change maintenance request status.")
        return redirect('properties:maintenance_request_list')

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(PropertyMaintenance.STATUS_CHOICES):
            maintenance.status = new_status
            if new_status == 'completed':
                maintenance.resolved_date = timezone.now()
            maintenance.save()

            # Create notification for tenant
            create_notification(
                recipient=maintenance.reported_by,
                notification_type='maintenance_status_update',
                title='Maintenance Request Status Updated',
                message=f'Your maintenance request for {maintenance.property.title} has been updated to {maintenance.get_status_display()}',
                related_object=maintenance
            )

            messages.success(request, f'Maintenance request status updated to {maintenance.get_status_display()}')
        else:
            messages.error(request, 'Invalid status selected')

    return redirect('properties:maintenance_request_detail', pk=pk)


@login_required
def property_manager_list(request):
    if not request.user.is_property_owner():
        messages.error(request, 'Access denied. Property owner privileges required.')
        return redirect('accounts:dashboard')

    owner = PropertyOwner.objects.get(user=request.user)
    managers = PropertyManager.objects.filter(
        assigned_properties__owner=owner
    ).distinct()

    return render(request, 'properties/property_manager_list.html', {
        'managers': managers
    })

@login_required
def property_manager_create(request):
    if not request.user.is_property_owner():
        messages.error(request, 'Access denied. Property owner privileges required.')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        if user_form.is_valid():
            with transaction.atomic():
                # Create user with property_manager type
                user = user_form.save(commit=False)
                user.user_type = 'property_manager'
                user.save()

                # Create property manager
                manager = PropertyManager.objects.create(user=user)

                # Assign properties
                property_ids = request.POST.getlist('properties')
                properties = Property.objects.filter(id__in=property_ids, owner__user=request.user)
                manager.assigned_properties.add(*properties)

                messages.success(request, 'Property manager created successfully.')
                return redirect('properties:property_manager_list')
    else:
        user_form = CustomUserCreationForm(initial={'user_type': 'property_manager'})

    owner = PropertyOwner.objects.get(user=request.user)
    properties = Property.objects.filter(owner=owner)

    return render(request, 'properties/property_manager_form.html', {
        'user_form': user_form,
        'properties': properties,
        'is_create': True
    })

@login_required
def property_manager_edit(request, pk):
    if not request.user.is_property_owner():
        messages.error(request, 'Access denied. Property owner privileges required.')
        return redirect('accounts:dashboard')

    manager = get_object_or_404(PropertyManager, pk=pk)
    if not manager.assigned_properties.filter(owner__user=request.user).exists():
        messages.error(request, 'Access denied. This manager is not assigned to your properties.')
        return redirect('properties:property_manager_list')

    if request.method == 'POST':
        property_ids = request.POST.getlist('properties')
        properties = Property.objects.filter(id__in=property_ids, owner__user=request.user)

        manager.assigned_properties.set(properties)
        messages.success(request, 'Property manager updated successfully.')
        return redirect('properties:property_manager_list')

    owner = PropertyOwner.objects.get(user=request.user)
    properties = Property.objects.filter(owner=owner)

    return render(request, 'properties/property_manager_form.html', {
        'manager': manager,
        'properties': properties,
        'is_create': False
    })

@login_required
def property_manager_delete(request, pk):
    if not request.user.is_property_owner():
        messages.error(request, 'Access denied. Property owner privileges required.')
        return redirect('accounts:dashboard')

    manager = get_object_or_404(PropertyManager, pk=pk)
    if not manager.assigned_properties.filter(owner__user=request.user).exists():
        messages.error(request, 'Access denied. This manager is not assigned to your properties.')
        return redirect('properties:property_manager_list')

    if request.method == 'POST':
        user = manager.user
        manager.delete()
        user.delete()
        messages.success(request, 'Property manager deleted successfully.')

    return redirect('properties:property_manager_list')

@login_required
def property_edit(request, pk):
    property = get_object_or_404(Property, pk=pk)

    # Check permissions
    if request.user != property.owner.user:
        return HttpResponseForbidden()

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES, instance=property)
        if form.is_valid():
            property = form.save()

            # Handle image uploads
            if request.FILES.getlist('images'):
                for image in request.FILES.getlist('images'):
                    PropertyImage.objects.create(
                        property=property,
                        image=image
                    )

            messages.success(request, 'Property updated successfully!')
            return redirect('properties:property_detail', pk=property.pk)
    else:
        form = PropertyForm(instance=property)

    return render(request, 'properties/property_form.html', {
        'form': form,
        'property': property,
        'title': 'Edit Property'
    })

@login_required
def property_delete(request, pk):
    property = get_object_or_404(Property, pk=pk)

    # Check if user is property owner
    if request.user != property.owner.user:
        return HttpResponseForbidden("Only property owner can delete properties.")

    # Check if property has active leases
    if property.leaseagreement_set.filter(end_date__gte=timezone.now()).exists():
        messages.error(request, 'Cannot delete property with active lease agreements.')
        return redirect('properties:property_detail', pk=pk)

    if request.method == 'POST':
        property.delete()
        messages.success(request, 'Property deleted successfully.')
        return redirect('properties:property_list')

    return render(request, 'properties/property_delete_confirm.html', {
        'property': property
    })

def get_property_analytics(property):
    """Generate analytics for a specific property"""
    # Get all leases for this property
    leases = LeaseAgreement.objects.filter(property_unit__property=property)

    # Calculate occupancy rate
    total_units = property.units.count()
    occupied_units = property.units.filter(is_available=False).count()
    occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0

    # Calculate average rent
    avg_rent = leases.filter(status='active').aggregate(Avg('monthly_rent'))['monthly_rent__avg'] or 0

    # Calculate revenue metrics
    current_month = datetime.now().replace(day=1)
    monthly_revenue = Invoice.objects.filter(
        lease_agreement__property_unit__property=property,
        issue_date__year=current_month.year,
        issue_date__month=current_month.month,
        status='paid'
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    # Calculate tenant metrics
    total_tenants = property.property_tenants.count()
    active_leases = leases.filter(status='active').count()
    tenant_turnover_rate = ((total_tenants - active_leases) / total_tenants * 100) if total_tenants > 0 else 0

    return {
        'occupancy_rate': round(occupancy_rate, 2),
        'avg_rent': round(avg_rent, 2),
        'monthly_revenue': monthly_revenue,
        'tenant_turnover_rate': round(tenant_turnover_rate, 2),
        'total_units': total_units,
        'occupied_units': occupied_units,
        'total_tenants': total_tenants,
        'active_leases': active_leases
    }

@login_required
def property_analytics(request, pk):
    """View for displaying property analytics"""
    property = get_object_or_404(Property, pk=pk)

    if request.user != property.owner.user:
        return HttpResponseForbidden()

    analytics_data = get_property_analytics(property)

    # Prepare historical data for charts
    lease_history = LeaseAgreement.objects.filter(
        property_unit__property=property
    ).values('start_date').annotate(
        rent=Avg('monthly_rent')
    ).order_by('start_date')

    context = {
        'property': property,
        'analytics': analytics_data,
    }

    return render(request, 'properties/property_analytics.html', context)



@login_required
def overall_property_analytics(request):
    if not request.user.is_property_owner:
        return HttpResponseForbidden()

    properties = Property.objects.filter(owner__user=request.user)

    total_properties = properties.count()
    total_units = 0
    total_occupied_units = 0
    total_revenue = Decimal('0.0')
    total_tenants = 0
    all_rents = []
    property_analytics = []

    for prop in properties:
        analytics = get_property_analytics(prop)
        monthly_revenue = analytics.get('monthly_revenue', Decimal('0.0'))

        # Add revenue into analytics to make template usage consistent
        analytics['monthly_revenue'] = float(monthly_revenue)

        property_analytics.append({
            'name': prop.title,
            'analytics': analytics
        })

        total_units += analytics.get('total_units', 0)
        total_occupied_units += analytics.get('occupied_units', 0)
        total_tenants += analytics.get('total_tenants', 0)
        total_revenue += monthly_revenue
        if analytics.get('avg_rent', 0) > 0:
            all_rents.append(float(analytics['avg_rent']))

    overall_occupancy = (total_occupied_units / total_units * 100) if total_units > 0 else 0
    overall_avg_rent = sum(all_rents) / len(all_rents) if all_rents else 0

    # --- Rent Trend (last 6 months)
    current_month = datetime.now().replace(day=1)
    six_months_ago = current_month - timedelta(days=180)

    lease_history = LeaseAgreement.objects.filter(
        property_unit__property__in=properties,
        start_date__gte=six_months_ago
    ).annotate(
        month=TruncMonth('start_date')
    ).values('month').annotate(
        avg_rent=Avg('monthly_rent')
    ).order_by('month')

    rent_chart_data = {
        'dates': [entry['month'].strftime('%b %Y') for entry in lease_history],
        'rents': [float(entry['avg_rent']) if entry['avg_rent'] else 0 for entry in lease_history]
    }

    # --- Revenue Trend (mocked here from rent * 10 logic)
    revenue_chart_data = {
        'dates': rent_chart_data['dates'],
        'amounts': [float(entry['avg_rent']) * 10 if entry['avg_rent'] else 0 for entry in lease_history]
    }

    # Sortings
    best_performing = sorted(property_analytics, key=lambda x: x['analytics'].get('monthly_revenue'), reverse=True)[:3]
    highest_occupancy = sorted(property_analytics, key=lambda x: x['analytics'].get('occupancy_rate', 0), reverse=True)[:3]

    context = {
        'total_properties': total_properties,
        'total_units': total_units,
        'total_occupied_units': total_occupied_units,
        'total_tenants': total_tenants,
        'overall_occupancy': round(overall_occupancy, 2),
        'overall_avg_rent': round(overall_avg_rent, 2),
        'property_analytics': property_analytics,
        'best_performing': best_performing,
        'highest_occupancy': highest_occupancy,
        'rent_chart_data': rent_chart_data,
        'revenue_chart_data': revenue_chart_data
    }

    return render(request, 'properties/property_analytics.html', context)


@login_required
def tenant_delete(request, tenant_pk):
    if not request.user.is_property_owner():
        return HttpResponseForbidden()
    tenant = get_object_or_404(Tenant, pk=tenant_pk)
    # Check if the tenant is associated with a property owned by the user
    tenant_property = TenantProperty.objects.filter(tenant=tenant, property__owner__user=request.user).first()
    if not tenant_property:
        return HttpResponseForbidden()
    # Check if the tenant has an active lease
    active_lease = LeaseAgreement.objects.filter(tenant=tenant, property__owner__user=request.user, status='active').first()
    if active_lease:
        messages.error(request, "Cannot delete tenant. The tenant is currently under an active lease.")
        return redirect('accounts:dashboard')
    if request.method == 'POST':
        # Optionally, update related lease agreements that are not active
        LeaseAgreement.objects.filter(tenant=tenant, property__owner__user=request.user).exclude(status='active').update(status='terminated')
        tenant_property.delete()  # Remove the tenant-property association
        messages.success(request, 'Tenant has been successfully removed from your property.')
        return redirect('accounts:dashboard')  # Adjust the redirect as needed
    return render(request, 'properties/confirm_tenant_delete.html', {'tenant': tenant})


from accounts.forms import TenantUpdateForm  # Adjust the import path if your forms are elsewhere
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponseForbidden
from accounts.models import Tenant
from properties.models import TenantProperty
from django.contrib import messages

@login_required
def tenant_edit(request, tenant_pk):
    if not request.user.is_property_owner():
        return HttpResponseForbidden()
    tenant = get_object_or_404(Tenant, pk=tenant_pk)
    tenant_property = TenantProperty.objects.filter(tenant=tenant, property__owner__user=request.user).first()
    if not tenant_property:
        return HttpResponseForbidden()

    if request.method == 'POST':
        form = TenantUpdateForm(request.POST, request.FILES, instance=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tenant information updated successfully.')
            return redirect('properties:property_detail', pk=tenant_property.property.pk)
    else:
        form = TenantUpdateForm(instance=tenant)

    return render(request, 'properties/tenant_edit.html', {'form': form, 'tenant': tenant})