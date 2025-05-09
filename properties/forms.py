from contextlib import nullcontext
from django import forms
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column
from .models import *
from decimal import Decimal

class PropertyForm(forms.ModelForm):
    images = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
            'multiple': False
        })
    )

    class Meta:
        model = Property
        fields = ['title', 'property_type', 'address', 'city', 'state', 'postal_code', 'description', 'images']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'address': forms.Textarea(attrs={'rows': 2}),
            'monthly_rent': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'square_feet': forms.NumberInput(attrs={'min': 0}),
            'bedrooms': forms.NumberInput(attrs={'min': 0}),
            'bathrooms': forms.NumberInput(attrs={'min': 0, 'step': '0.5'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Column('title', css_class='col-md-8'),
                Column('property_type', css_class='col-md-4'),
            ),
            Row(
                Column('address', css_class='col-md-12'),
            ),
            Row(
                Column('city', css_class='col-md-4'),
                Column('state', css_class='col-md-4'),
                Column('postal_code', css_class='col-md-4'),
            ),
            Row(
                Column('description', css_class='col-md-8'),
                Column('images', css_class='col-md-4'),
            ),
        )

        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def save(self, commit=True):
        property_instance = super().save(commit=commit)

        if commit and self.cleaned_data.get('images'):
            for image in self.files.getlist('images'):
                PropertyImage.objects.create(
                    property=property_instance,
                    image=image
                )

        return property_instance

class PropertyImageForm(forms.ModelForm):
    class Meta:
        model = PropertyImage
        fields = ['image', 'caption']
        widgets = {
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'caption': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Image caption (optional)'
            })
        }

class CommercialUnitForm(forms.ModelForm):
    bedrooms = forms.IntegerField(initial=0, widget=forms.HiddenInput())
    bathrooms = forms.IntegerField(initial=0, widget=forms.HiddenInput())
    def __init__(self, *args, **kwargs):
        self.property_instance = kwargs.pop('property_instance', None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.HiddenInput)):
                field.widget.attrs['class'] = 'form-control'

        # Add help text
        self.fields['unit_number'].help_text = 'Unique identifier for this commercial unit'
        self.fields['monthly_rent'].help_text = 'Monthly rental amount for this unit'
        self.fields['square_feet'].help_text = 'Total commercial space in square feet'
        self.fields['is_available'].help_text = 'Whether this unit is available for lease'

    def clean(self):
        cleaned_data = super().clean()
        if self.property_instance and self.property_instance.property_type != 'commercial':
            raise forms.ValidationError("This form is only for commercial units")
        # Always set bedrooms and bathrooms to 0 for commercial units
        cleaned_data['bedrooms'] = 0
        cleaned_data['bathrooms'] = 0
        return cleaned_data

    class Meta:
        model = PropertyUnit
        fields = ['unit_number', 'monthly_rent', 'square_feet', 'is_available', 'business_type', 'bedrooms', 'bathrooms']
        widgets = {
            'monthly_rent': forms.NumberInput(attrs={'min': 0}),
            'square_feet': forms.NumberInput(attrs={'min': 0}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class PropertyUnitForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.property_instance = kwargs.pop('property_instance', None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-control'

        # Add help text
        self.fields['unit_number'].help_text = 'Unique identifier for this residential unit'
        self.fields['monthly_rent'].help_text = 'Monthly rental amount for this unit'
        self.fields['bedrooms'].help_text = 'Number of bedrooms in this unit'
        self.fields['bathrooms'].help_text = 'Number of bathrooms in this unit'
        self.fields['square_feet'].help_text = 'Total living space in square feet'
        self.fields['kitchen'].help_text = 'Number of kitchens in this unit'

    def clean(self):
        cleaned_data = super().clean()
        if self.property_instance and self.property_instance.property_type != 'residential':
            raise forms.ValidationError("This form is only for residential units")
        if not cleaned_data.get('bedrooms'):
            raise forms.ValidationError({'bedrooms': 'Bedrooms are required for residential units'})
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.property_instance:
            instance.property = self.property_instance
        if commit:
            instance.save()
        return instance

    class Meta:
        model = PropertyUnit
        fields = ['unit_number', 'monthly_rent', 'bedrooms',
                 'bathrooms', 'kitchen', 'square_feet']
        widgets = {
            'bathrooms': forms.NumberInput(attrs={'min': 0, 'step': '0.5'}),
            'monthly_rent': forms.NumberInput(attrs={'min': 0}),
            'square_feet': forms.NumberInput(attrs={'min': 0}),
            'bedrooms': forms.NumberInput(attrs={'min': 0}),
        }

class LeaseAgreementForm(forms.ModelForm):
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    property_unit = forms.ModelChoiceField(
        queryset=PropertyUnit.objects.none(),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'placeholder': 'Select Unit'
        })
    )

    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'placeholder': 'Select Tenant'
        })
    )

    class Meta:
        model = LeaseAgreement
        fields = ['tenant', 'start_date', 'end_date', 'monthly_rent', 'property_unit', 'rent_due_day',
                 'security_deposit', 'bank_account']
        widgets = {
            'start_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'end_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'monthly_rent': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01'
            }),
            'rent_due_day': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '31'
            }),
            'security_deposit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01'
            })
        }

    def __init__(self, *args, **kwargs):
        # Extract property from kwargs before calling super()
        self.property = kwargs.pop('property', None)
        super().__init__(*args, **kwargs)

        if self.property:
            # Filter available units for this property
            self.fields['property_unit'].queryset = self.property.units.filter(
                is_available=True
            ).exclude(
                # Exclude units that already have active leases
                id__in=LeaseAgreement.objects.filter(
                    property_unit__property=self.property,
                    status='active'
                ).values('property_unit_id')
            )

            # Filter only tenants that have an active TenantProperty relationship with this property
            self.fields['tenant'].queryset = Tenant.objects.filter(
                tenant_properties__property=self.property,
                tenant_properties__status='active',
                user__is_active=True
            ).distinct().exclude(
                # Exclude tenants that already have active leases in this property
                id__in=LeaseAgreement.objects.filter(
                    property_unit__property=self.property,
                    status='active'
                ).values('tenant_id')
            )

            # Filter active bank accounts for this property
            self.fields['bank_account'].queryset = self.property.bank_accounts.filter(
                status='Active'
            )

    def clean(self):
        cleaned_data = super().clean()
        property_unit = cleaned_data.get('property_unit')
        tenant = cleaned_data.get('tenant')

        if property_unit and tenant:
            # Check if the unit is still available
            if not property_unit.is_available:
                raise forms.ValidationError("This unit is no longer available.")

            # Check if tenant already has an active lease in this property
            if LeaseAgreement.objects.filter(
                property_unit__property=self.property,
                tenant=tenant,
                status='active'
            ).exists():
                raise forms.ValidationError("This tenant already has an active lease in this property.")

        return cleaned_data

class PropertyMaintenanceForm(forms.ModelForm):
    PRIORITY_CHOICES = [
        ('low', 'Low - Regular maintenance or minor issues'),
        ('medium', 'Medium - Issues affecting comfort but not safety'),
        ('high', 'High - Urgent issues affecting safety or habitability')
    ]

    title = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Brief title for the maintenance issue'
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Describe the maintenance issue in detail'
    )
    priority = forms.ChoiceField(
        choices=PRIORITY_CHOICES,
        initial='medium',
        widget=forms.RadioSelect,
        help_text='Select the urgency level of this maintenance request'
    )
    photos = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'multiple': False}),
        help_text='Upload photos of the issue (optional)'
    )
    preferred_time = forms.CharField(
        required=False,
        help_text='Preferred time for maintenance visit (optional)',
        widget=forms.TextInput(attrs={'placeholder': 'e.g., Weekday mornings'})
    )
    tenant_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Any additional notes or special instructions'
    )

    class Meta:
        model = PropertyMaintenance
        fields = ['title', 'description', 'priority', 'photos', 'preferred_time', 'tenant_notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes to form fields
        for field_name, field in self.fields.items():
            if not isinstance(field.widget, forms.RadioSelect):
                field.widget.attrs['class'] = 'form-control'
            else:
                field.widget.attrs['class'] = 'form-check-input'

    def clean_photos(self):
        photos = self.cleaned_data.get('photos')
        if photos:
            # Check file size (limit to 5MB)
            if photos.size > 5 * 1024 * 1024:
                raise forms.ValidationError('Image file size must be less than 5MB')
            # Check file type
            valid_types = ['image/jpeg', 'image/png', 'image/gif']
            if photos.content_type not in valid_types:
                raise forms.ValidationError('Only JPEG, PNG and GIF files are allowed')
        return photos

class PropertySearchForm(forms.Form):
    PRICE_CHOICES = [
        ('', 'Any Price'),
        ('0-1000', 'Under $1,000'),
        ('1000-2000', '$1,000 - $2,000'),
        ('2000-3000', '$2,000 - $3,000'),
        ('3000-4000', '$3,000 - $4,000'),
        ('4000-5000', '$4,000 - $5,000'),
        ('5000+', '$5,000+')
    ]

    keyword = forms.CharField(required=False, widget=forms.TextInput(
        attrs={'class': 'form-control', 'placeholder': 'Search by keyword...'}
    ))
    property_type = forms.ChoiceField(
        choices=[('', 'All Types')] + list(Property.PROPERTY_TYPE_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    city = forms.CharField(required=False, widget=forms.TextInput(
        attrs={'class': 'form-control', 'placeholder': 'City'}
    ))
    price_range = forms.ChoiceField(
        choices=PRICE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    bedrooms = forms.ChoiceField(
        choices=[('', 'Any')] + [(i, i) for i in range(1, 6)] + [(6, '6+')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['title', 'account_type', 'status', 'account_mode', 'client_id', 'secret_key']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter title'
            }),
            'account_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'account_mode': forms.RadioSelect(),
            'client_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter client id'
            }),
            'secret_key': forms.PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter secret key'
            }, render_value=True),
        }

    def __init__(self, *args, **kwargs):
        self.property = kwargs.pop('property', None)
        super().__init__(*args, **kwargs)

        # Set default form field classes
        for field in self.fields.values():
            if not isinstance(field.widget, forms.RadioSelect):
                field.widget.attrs['class'] = 'form-control'

        # Set choices for account type based on property settings
        if self.property:
            self.fields['account_type'].choices = [
                ('stripe', 'Stripe'),
                ('paypal', 'PayPal'),
                ('razorpay', 'Razorpay')
            ]
