from django.shortcuts import render, redirect, get_object_or_404,reverse
from .models import Notification
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q
from django.views.generic import CreateView, UpdateView
from django.urls import reverse_lazy
from .forms import (
    CustomUserCreationForm, PropertyOwnerRegistrationForm,
    TenantRegistrationForm, PropertyOwnerUpdateForm,
    TenantUpdateForm, UserLoginForm, SubscriptionForm
)
from payments.models import Payment
from .models import CustomUser, PropertyOwner, Tenant, Subscription, PropertyOwnerSubscription
from properties.models import (
    LeaseAgreement, Property, TenantProperty, PropertyMaintenance,
    PropertyManager
)
from payments.models import Payment,Invoice
from django.utils import timezone
from datetime import datetime, timedelta
from django.conf import settings
import stripe
from django.db import transaction
import json
from django.core.serializers.json import DjangoJSONEncoder

from django.contrib.auth.views import PasswordResetView
from .forms import UsernamePasswordResetForm

from django.urls import reverse_lazy

class UsernamePasswordResetView(PasswordResetView):
    form_class = UsernamePasswordResetForm
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.html'
    success_url = reverse_lazy('accounts:password_reset_done')



@login_required
def superadmin_dashboard(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Superadmin privileges required.')
        return redirect('accounts:dashboard')

    property_owners = PropertyOwner.objects.all()
    subscription_packages = Subscription.objects.all()
    active_subscriptions = PropertyOwnerSubscription.objects.filter(is_active=True).count()

    context = {
        'property_owners': property_owners,
        'subscription_packages': subscription_packages,
        'active_subscriptions': active_subscriptions,
    }
    return render(request, 'accounts/superadmin_dashboard.html', context)

@login_required
def subscription_create(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Superadmin privileges required.')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Subscription package created successfully.')
            return redirect('accounts:superadmin_dashboard')
    else:
        form = SubscriptionForm()

    return render(request, 'accounts/subscription_form.html', {'form': form})


from django.shortcuts import render
from django.db.models import Exists, OuterRef

@login_required
def subscription_delete(request, subscription_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Superadmin privileges required.')
        return redirect('accounts:dashboard')

    subscription = get_object_or_404(Subscription, id=subscription_id)

    # Check if the subscription is being used by any property owner
    is_in_use = PropertyOwnerSubscription.objects.filter(subscription=subscription).exists()

    if request.method == 'POST':
        if is_in_use:
            messages.error(request, 'Cannot delete this subscription because it is currently active for one or more property owners.')
            return redirect('accounts:dashboard')

        subscription.delete()
        messages.success(request, 'Subscription package deleted successfully.')
        return redirect('accounts:dashboard')

    context = {
        'subscription': subscription,
        'is_in_use': is_in_use
    }
    return render(request, 'accounts/confirm_delete_subscription.html', context)



@login_required
def dashboard(request):
    user = request.user
    context = {
        'user': user,
    }

    if user.is_superuser:
        # Superadmin: Show property owners list and system stats
        context['property_owners'] = PropertyOwner.objects.all()
        context['subscription_packages'] = Subscription.objects.all()
        return render(request, 'accounts/superadmin_dashboard.html', context)

    # Check user type and display appropriate dashboard
    if request.user.is_property_owner():
        try:
            # Get the property owner
            property_owner = PropertyOwner.objects.get(user=request.user)
            context = {
                'property_owner': property_owner,
                'properties': Property.objects.filter(owner=property_owner),
            }

            # Add total properties and tenants
            context['total_properties'] = context['properties'].count()
            context['total_tenants'] = Tenant.objects.filter(
                leaseagreement__property_unit__property__owner=property_owner,
                leaseagreement__status='active'
            ).distinct().count()

            # Add recent lease agreements
            context['lease_agreements'] = LeaseAgreement.objects.filter(
                property_unit__property__owner=property_owner
            ).order_by('-created_at')[:5]

            # Add recent maintenance requests
            context['maintenance_requests'] = PropertyMaintenance.objects.filter(
                property__owner=property_owner
            ).order_by('-reported_date')[:5]

                        # Get recent invoices
            context['invoice_total'] = Invoice.objects.filter(
            property__owner=property_owner
            ).aggregate(total=Sum('total_amount'))['total'] or 0


            return render(request, 'accounts/property_owner_dashboard.html', context)

        except PropertyOwner.DoesNotExist:
            messages.warning(request, 'Please complete your property owner profile.')
            return redirect('accounts:complete_profile')

    elif request.user.is_tenant():
        try:
            tenant = Tenant.objects.get(user=request.user)
            context['tenant'] = tenant
            context['lease_agreements'] = LeaseAgreement.objects.filter(tenant=tenant)

            # Get invoices instead of payments
            context['invoices'] = Invoice.objects.filter(
                lease_agreement__tenant=tenant
            ).order_by('-created_at')[:5]

            context['pending_payments'] = Invoice.objects.filter(
                lease_agreement__tenant=tenant,
                status='pending'
            ).count()

            context['payments'] = Invoice.objects.filter(
                lease_agreement__tenant=tenant,
                status='paid'
            )

            return render(request, 'accounts/tenant_dashboard.html', context)

        except Tenant.DoesNotExist:
            messages.warning(request, 'Please complete your tenant profile.')
            return redirect('accounts:complete_profile')

    elif request.user.is_property_manager():
        try:
            property_manager = PropertyManager.objects.get(user=request.user)
            context['property_manager'] = property_manager

            # Get assigned properties
            context['properties'] = property_manager.assigned_properties.all()
            context['total_properties'] = context['properties'].count()

            # Get maintenance requests for assigned properties
            context['maintenance_requests'] = PropertyMaintenance.objects.filter(
                property__in=context['properties']
            ).order_by('-reported_date')[:10]

            # Count maintenance requests by status
            context['pending_maintenance'] = PropertyMaintenance.objects.filter(
                property__in=context['properties'],
                status='pending'
            ).count()

            context['in_progress_maintenance'] = PropertyMaintenance.objects.filter(
                property__in=context['properties'],
                status='in_progress'
            ).count()

            return render(request, 'accounts/property_manager_dashboard.html', context)

        except PropertyManager.DoesNotExist:
            messages.warning(request, 'Please complete your property manager profile.')
            return redirect('accounts:complete_profile')

    # If user type is not set
    return redirect('accounts:select_user_type')

def register_property_owner(request):
    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST, request.FILES)
        owner_form = PropertyOwnerRegistrationForm(request.POST)
        if user_form.is_valid() and owner_form.is_valid():
            try:
                user = user_form.save(commit=False)
                user.user_type = 'property_owner'
                user.save()
                owner = owner_form.save(commit=False)
                owner.user = user
                owner.save()
                login(request, user)  # Log the user in
                messages.success(request, 'Registration successful! Please select a subscription plan.')
                return redirect('/payment')
            except Exception as e:
                messages.error(request, f'Registration failed: {str(e)}')
        else:
            for field, errors in user_form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
            for field, errors in owner_form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        user_form = CustomUserCreationForm(initial={'user_type': 'property_owner'})
        owner_form = PropertyOwnerRegistrationForm()

    return render(request, 'accounts/register_property_owner.html', {
        'user_form': user_form,
        'owner_form': owner_form
    })

def register_tenant(request, property_id):
    # Get the property and verify ownership
    property = get_object_or_404(Property, id=property_id)

    # Only allow property owners who own this property
    if not request.user.is_authenticated or not request.user.is_property_owner():
        messages.error(request, 'Only property owners can register tenants.')
        return redirect('accounts:login')

    if property.owner.user != request.user:
        messages.error(request, 'You can only register tenants for your own properties.')
        return redirect('properties:property_list')

    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST, request.FILES)
        tenant_form = TenantRegistrationForm(request.POST, request.FILES)

        if user_form.is_valid() and tenant_form.is_valid():
            try:
                with transaction.atomic():
                    # Create user account
                    user = user_form.save(commit=False)
                    user.user_type = 'tenant'
                    user.save()

                    # Create tenant profile
                    tenant = tenant_form.save(commit=False)
                    tenant.user = user
                    tenant.save()

                    # Create tenant-property relationship
                    TenantProperty.objects.create(
                        tenant=tenant,
                        property=property,
                        status='active',  # Automatically active since property owner is creating it
                        start_date=timezone.now()
                    )

                    # Send welcome email
                    from utils.email_utils import send_tenant_creation_email
                    try:
                        send_tenant_creation_email(tenant)
                    except Exception as e:
                        messages.warning(request, f'Tenant created but email notification failed: {str(e)}')

                    messages.success(request, 'Tenant registered successfully!')
                    return redirect('properties:property_detail', pk=property_id)

            except Exception as e:
                messages.error(request, f'Error creating tenant account: {str(e)}')

        else:
            for field, errors in user_form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
            for field, errors in tenant_form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        # Initialize forms with default tenant type
        user_form = CustomUserCreationForm(initial={
            'user_type': 'tenant',
        })
        tenant_form = TenantRegistrationForm()

    context = {
        'user_form': user_form,
        'tenant_form': tenant_form,
        'property': property,
        'is_owner_registration': True,
        'page_title': f'Register New Tenant for {property.title}'
    }

    return render(request, 'accounts/register_tenant.html', context)


def user_login(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    form = UserLoginForm()
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        # First try to authenticate with username
        user = authenticate(username=username, password=password)

        # If that fails, try to authenticate with email
        if not user:
            try:
                # Use filter instead of get to handle multiple users
                users = CustomUser.objects.filter(email=username)
                if users.exists():
                    # Try to authenticate with each user's credentials
                    for user_obj in users:
                        user = authenticate(username=user_obj.username, password=password)
                        if user:
                            break  # Found a valid user
            except Exception as e:
                user = None

        if not user:
            messages.error(request, 'Invalid email/username or password.')
            return render(request, 'accounts/login.html', {'form': form})

        login(request, user)
        messages.success(request, 'Login successful!')

        # Check if user is a property owner and redirect to subscription
        if hasattr(user, 'property_owner'):
            return redirect('accounts:payment')

        return redirect('accounts:dashboard')

    return render(request, 'accounts/login.html', {'form': form})


@login_required
def user_logout(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('/')

@login_required
def profile(request):
    user = request.user
    if user.is_property_owner():
        owner = PropertyOwner.objects.get(user=user)
        if request.method == 'POST':
            form = PropertyOwnerUpdateForm(request.POST, instance=owner)
            if form.is_valid():
                form.save()
                user.email = form.cleaned_data['email']
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('profile')
        else:
            form = PropertyOwnerUpdateForm(instance=owner)
        return render(request, 'accounts/profile.html', {'form': form})
    else:
        tenant = Tenant.objects.get(user=user)
        if request.method == 'POST':
            form = TenantUpdateForm(request.POST, instance=tenant)
            if form.is_valid():
                form.save()
                user.email = form.cleaned_data['email']
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('profile')
        else:
            form = TenantUpdateForm(instance=tenant)
        return render(request, 'accounts/profile.html', {'form': form})


from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Prefetch
from properties.models import Tenant, LeaseAgreement  # adjust if your import paths differ
from payments.models import Invoice  # Adjust path as needed
from django.db.models import Prefetch

@login_required
def tenant_list(request):
    if request.user.is_superuser:
        tenants = Tenant.objects.select_related('user').prefetch_related(
            Prefetch('leaseagreement_set', queryset=LeaseAgreement.objects.select_related('property', 'property_unit'))
        ).all()
    elif request.user.is_property_owner():
        tenants = Tenant.objects.select_related('user').prefetch_related(
            Prefetch('leaseagreement_set', queryset=LeaseAgreement.objects.select_related('property', 'property_unit'))
        ).filter(leaseagreement__property__owner=request.user.propertyowner).distinct()
    else:
        messages.error(request, 'Access denied. You do not have permission to view tenants.')
        return redirect('accounts:dashboard')

    # Prepare lease details per tenant
    tenant_data = []
    for tenant in tenants:
        leases = tenant.leaseagreement_set.all()
        lease_info = []
        for lease in leases:
            # Get latest invoice for this lease
            latest_invoice = Invoice.objects.filter(lease_agreement=lease).order_by('-issue_date').first()
            payment_status = latest_invoice.status if latest_invoice else 'No Invoice'

            lease_info.append({
                'property': lease.property.title,
                'unit': lease.property_unit.unit_number if lease.property_unit else 'N/A',
                'lease_status': 'Active' if lease.status == 'active' else 'Inactive',
                'payment_status': payment_status
            })

        tenant_data.append({
            'tenant': tenant,
            'leases': lease_info
        })

    return render(request, 'accounts/tenant_list.html', {
        'tenant_data': tenant_data
    })


@login_required
def subscription_view(request):
    if not request.user.is_property_owner():
        messages.error(request, "Access denied. Only property owners can access subscription plans.")
        return redirect('home')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    subscription_plans = {}
    selected_subscription_id = request.session.get('selected_subscription_id')

    try:
        # If there's a price_id in the query params, create a checkout session
        if request.method == 'GET' and 'price_id' in request.GET:
            price_id = request.GET.get('price_id')
            subscription = Subscription.objects.get(stripe_price_id=price_id, is_active=True)

            # Create Stripe Checkout Session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': subscription.stripe_price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=request.build_absolute_uri(reverse('accounts:payment_successful')) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=request.build_absolute_uri(reverse('accounts:payment_cancelled')),
                client_reference_id=request.user.propertyowner.id
            )

            # Store subscription details in session
            request.session['subscription_id'] = subscription.id
            request.session['subscription_duration'] = subscription.duration_months * 30  # Convert months to days

            return JsonResponse({'sessionId': checkout_session.id})

        # Get all active subscriptions
        subscriptions = Subscription.objects.filter(is_active=True)
        for subscription in subscriptions:
            subscription_plans[subscription.id] = {
                'id': subscription.id,
                'name': subscription.name,
                'price': float(subscription.price),
                'duration_months': subscription.duration_months,
                'max_properties': subscription.max_properties,
                'max_units': subscription.max_units,
                'description': subscription.description,
                'price_id': subscription.stripe_price_id,
            }

        # If there's a selected subscription, move it to the top
        if selected_subscription_id:
            selected_plan = subscription_plans.pop(int(selected_subscription_id), None)
            if selected_plan:
                new_plans = {int(selected_subscription_id): selected_plan}
                new_plans.update(subscription_plans)
                subscription_plans = new_plans
                # Clear the session variable
                del request.session['selected_subscription_id']

    except Subscription.DoesNotExist:
        messages.error(request, 'Invalid subscription plan')
        return redirect('accounts:dashboard')
    except Exception as e:
        messages.error(request, f'Error processing payment: {str(e)}')
        return redirect('accounts:dashboard')

    context = {
        'subscription_plans': subscription_plans,
        'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY,
        'selected_subscription_id': selected_subscription_id
    }
    return render(request, 'accounts/subscription.html', context)

@login_required
def payment_successful(request):
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.error(request, 'No session ID provided')
        return redirect('accounts:dashboard')

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)

        # Get subscription from session metadata
        subscription_id = request.session.get('subscription_id')
        if not subscription_id:
            messages.error(request, 'No subscription found')
            return redirect('accounts:dashboard')

        subscription = Subscription.objects.get(id=subscription_id)
        property_owner = PropertyOwner.objects.get(user=request.user)

        if session.payment_status == 'paid':
            # Cancel current active subscription if exists
            current_subscription = PropertyOwnerSubscription.objects.filter(
                property_owner=property_owner,
                status='active',
                end_date__gt=timezone.now()
            ).first()

            if current_subscription:
                # Cancel the subscription in Stripe if it exists
                if current_subscription.stripe_subscription_id:
                    try:
                        stripe.Subscription.delete(current_subscription.stripe_subscription_id)
                    except stripe.error.StripeError:
                        # If there's an error deleting from Stripe, continue anyway
                        pass

                # Mark current subscription as cancelled
                current_subscription.status = 'cancelled'
                current_subscription.cancelled_at = timezone.now()
                current_subscription.save()

            # Calculate end date based on subscription duration
            duration_days = subscription.duration_months * 30
            end_date = timezone.now() + timezone.timedelta(days=duration_days)

            # Create new property owner subscription
            owner_subscription = PropertyOwnerSubscription.objects.create(
                property_owner=property_owner,
                subscription=subscription,
                status='active',
                start_date=timezone.now(),
                end_date=end_date,
                payment_status='completed',
                payment_amount=subscription.price,
                payment_date=timezone.now(),
                stripe_payment_intent_id=session.payment_intent,
                stripe_customer_id=session.customer,
                stripe_subscription_id=session.subscription
            )

            # Create payment record
            Payment.objects.create(
                payment_type='subscription',
                amount=subscription.price,
                payment_date=timezone.now(),
                status='completed',
                payment_method='stripe',
                transaction_id=session.payment_intent,
                stripe_payment_intent_id=session.payment_intent,
                stripe_payment_method_id=session.payment_intent,
                paid_by=request.user
            )

            messages.success(request, f'Payment successful! Your subscription has been upgraded to {subscription.name}.')

            # Clear session data
            if 'subscription_id' in request.session:
                del request.session['subscription_id']
            if 'subscription_duration' in request.session:
                del request.session['subscription_duration']

            return redirect('accounts:subscription_list')
        else:
            messages.error(request, 'Payment was not completed successfully')
            return redirect('accounts:subscription_list')

    except stripe.error.StripeError as e:
        messages.error(request, f'Stripe error: {str(e)}')
        return redirect('accounts:subscription_list')
    except Exception as e:
        messages.error(request, f'Error processing payment: {str(e)}')
        return redirect('accounts:subscription_list')

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
    endpoint_secret = STRIPE_ENDPOINT_SECRET
    try:
        event = stripe.Webhook.construct_event(payload,sig_header,endpoint_secret)
    except:
        return HttpResponse(status=400)

    if event['type'] == 'checkout_session.completed':
        print(event)
        print('payment ws succesful')
    return HttpResponse(status=200 )

def create_subscription(request):
    checkout_session_id = request.GET.get('session_id', None)
    return redirect('my_sub')




def payment_cancelled(request):
    return render(request, 'accounts/cancel.html')

@login_required
def create_notification(request, message):
    notification = Notification(user=request.user, message=message)
    notification.save()
    return redirect('notifications_list')

@login_required
def notifications_list(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-timestamp')
    notifications_data = [
        {
            'id': notification.id,
            'message': notification.message,
            'is_read': notification.is_read,
            'timestamp': notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }
        for notification in notifications
    ]
    return JsonResponse({'notifications': notifications_data})

@login_required
def mark_as_read(request, notification_id):
    notification = Notification.objects.get(id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    return redirect('notifications_list')

@login_required
def property_analytics(request):
    if not request.user.is_property_owner():
        messages.error(request, 'Access denied. Property owner privileges required.')
        return redirect('accounts:dashboard')

    owner = PropertyOwner.objects.get(user=request.user)

    # Get date range from request or default to last 30 days
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)

    # Get all invoices for this owner
    invoices = Invoice.objects.filter(
        property__owner=owner,
        created_at__range=[start_date, end_date]
    )

    # Calculate total revenue
    total_revenue = invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # Calculate paid vs pending amounts
    paid_amount = invoices.filter(status='paid').aggregate(
        Sum('total_amount'))['total_amount__sum'] or 0
    pending_amount = invoices.filter(status='pending').aggregate(
        Sum('total_amount'))['total_amount__sum'] or 0

    # Get revenue by property
    property_revenue = list(invoices.values('property__title').annotate(
        total=Sum('total_amount')
    ).order_by('-total'))

    # Get payment type distribution
    payment_types = list(invoices.values('payment_type').annotate(
        count=Sum('total_amount')
    ).order_by('-count'))

    # Get monthly trend
    monthly_trend = list(invoices.filter(
        status='paid'
    ).values('created_at__month').annotate(
        total=Sum('total_amount')
    ).order_by('created_at__month'))

    context = {
        'total_revenue': total_revenue,
        'paid_amount': paid_amount,
        'pending_amount': pending_amount,
        'property_revenue': json.dumps(property_revenue, cls=DjangoJSONEncoder),
        'payment_types': json.dumps(payment_types, cls=DjangoJSONEncoder),
        'monthly_trend': json.dumps(monthly_trend, cls=DjangoJSONEncoder),
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(request, 'accounts/property_analytics.html', context)

@login_required
def subscription_edit(request, package_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Superadmin privileges required.')
        return redirect('accounts:dashboard')

    package = get_object_or_404(Subscription, id=package_id)

    if request.method == 'POST':
        print("POST data:", request.POST)
        form = SubscriptionForm(request.POST, instance=package)
        if form.is_valid():
            form.save()
            messages.success(request, 'Package updated successfully.')
            return redirect('accounts:dashboard')
        else:
            print("Form errors:", form.errors)
    else:
        form = SubscriptionForm(instance=package)

    return render(request, 'accounts/subscription_form.html', {
        'form': form,
        'package': package,
        'is_edit': True
    })

@login_required
def create_subscription(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. Superadmin privileges required.')
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        try:
            subscription = Subscription(
                name=request.POST.get('name'),
                type=request.POST.get('type'),
                price=request.POST.get('price'),
                description=request.POST.get('description'),
                max_properties=request.POST.get('max_properties', 1),
                max_units=request.POST.get('max_units', 1),
                duration_months=request.POST.get('duration_months', 1),
                stripe_price_id=request.POST.get('stripe_price_id'),
                features={"basic_features": ["feature1", "feature2"]},  # Default features
                is_active=request.POST.get('is_active', False) == 'on'
            )
            subscription.save()
            messages.success(request, f'Subscription package "{subscription.name}" created successfully.')
            return redirect('accounts:dashboard')
        except Exception as e:
            messages.error(request, f'Error creating subscription: {str(e)}')

    form = SubscriptionForm()
    context = {
        'form': form
    }
    return render(request, 'accounts/create_subscription.html', context)

@login_required
def property_owner_detail(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to view this page.")
        return redirect('accounts:dashboard')

    owner = get_object_or_404(PropertyOwner, pk=pk)
    properties = Property.objects.filter(owner=owner)

    return render(request, 'accounts/property_owner_detail.html', {
        'owner': owner,
        'properties': properties,
    })

@login_required
def verify_property_owner(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        owner = get_object_or_404(PropertyOwner, pk=pk)
        owner.verification_status = True
        owner.save()

        # Create notification for property owner
        """create_notification(
            request,
            recipient=owner.user,
            notification_type='account_verified',
            title='Account Verified',
            message='Your property owner account has been verified by the administrator.',
            related_object=owner
        )"""

        messages.success(request, f'Property owner {owner.user.get_full_name()} has been verified.')

    return redirect('accounts:dashboard')

from django.shortcuts import render

@login_required
def delete_property_owner(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect('accounts:dashboard')

    owner = get_object_or_404(PropertyOwner, pk=pk)
    user = owner.user

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Delete properties and related data first
                properties = Property.objects.filter(owner=owner)
                for property in properties:
                    property.delete()

                # Delete the property owner and user
                owner.delete()
                user.delete()

                messages.success(request, f'Property owner {user.get_full_name()} has been deleted.')
                return redirect('accounts:dashboard')
        except Exception as e:
            messages.error(request, f'Error deleting property owner: {str(e)}')
            return redirect('accounts:dashboard')

    # Render confirmation page
    context = {
        'owner': owner,
        'user_full_name': user.get_full_name(),
    }
    return render(request, 'accounts/confirm_delete_owner.html', context)


@login_required
def subscription_list(request):
    if not request.user.is_property_owner():
        messages.error(request, "Access denied. Only property owners can view subscriptions.")
        return redirect('home')

    subscriptions = Subscription.objects.filter(is_active=True)
    current_subscription = None

    try:
        current_subscription = PropertyOwnerSubscription.objects.filter(
            property_owner=request.user.propertyowner,
            status='active',
            end_date__gt=timezone.now()
        ).first()
    except PropertyOwnerSubscription.DoesNotExist:
        pass

    context = {
        'subscriptions': subscriptions,
        'current_subscription': current_subscription
    }
    return render(request, 'accounts/subscription_list.html', context)

@login_required
def upgrade_subscription(request, subscription_id):
    if not request.user.is_property_owner():
        messages.error(request, "Access denied. Only property owners can upgrade subscriptions.")
        return redirect('home')

    try:
        new_subscription = Subscription.objects.get(id=subscription_id, is_active=True)
        property_owner = request.user.propertyowner

        # Redirect to subscription view with the selected subscription
        request.session['selected_subscription_id'] = subscription_id
        return redirect('accounts:subscription')

    except Subscription.DoesNotExist:
        messages.error(request, "Invalid subscription selected.")
        return redirect('accounts:subscription_list')
    except Exception as e:
        messages.error(request, f"Error upgrading subscription: {str(e)}")
        return redirect('accounts:subscription_list')

@login_required
def select_user_type(request):
    """View for selecting user type (property owner, tenant, or property manager)"""
    if request.user.is_property_owner():
        return redirect('accounts:dashboard')
    elif request.user.is_tenant():
        return redirect('accounts:dashboard')
    elif request.user.is_property_manager():
        return redirect('accounts:dashboard')

    return render(request, 'accounts/select_user_type.html')