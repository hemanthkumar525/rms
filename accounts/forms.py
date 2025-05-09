from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Hidden
from .models import CustomUser, PropertyOwner, Tenant, Subscription

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email', 'first_name', 'last_name', 'phone_number',
                 'address', 'profile_picture')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Column('first_name', css_class='form-group col-md-6 mb-3'),
                Column('last_name', css_class='form-group col-md-6 mb-3'),
            ),
            'email',
            'username',
            Row(
                Column('password1', css_class='form-group col-md-6 mb-3'),
                Column('password2', css_class='form-group col-md-6 mb-3'),
            ),
            'phone_number',
            'address',
            'profile_picture',
            Hidden('user_type', 'property_owner')
        )
        # Add Bootstrap classes
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm

class UsernamePasswordResetForm(PasswordResetForm):
    username = forms.CharField(label="Username", max_length=150)
    email = forms.EmailField(widget=forms.HiddenInput())  # We'll set this in the clean method

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = False  # We'll get the email from username

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        if username:
            UserModel = get_user_model()
            try:
                user = UserModel.objects.get(username=username)
                if user.email:
                    cleaned_data['email'] = user.email
                else:
                    raise forms.ValidationError("This user doesn't have an email address.")
            except UserModel.DoesNotExist:
                raise forms.ValidationError("No user found with this username.")
        return cleaned_data

    def get_users(self, email):
        UserModel = get_user_model()
        active_users = UserModel._default_manager.filter(**{
            '%s__iexact' % UserModel.get_email_field_name(): email,
            'is_active': True,
        })
        return (
            u for u in active_users
            if u.has_usable_password() and
            _unicode_ci_compare(email, getattr(u, UserModel.get_email_field_name()))
        )
    username = forms.CharField(label="Username", max_length=150)

    def get_users(self, username):
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(username=username)
            if user.email:
                return [user]
        except UserModel.DoesNotExist:
            return []
        return []

    def save(self, domain_override=None,
             subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=None,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None):
        username = self.cleaned_data["username"]
        for user in self.get_users(username):
            reset_form = PasswordResetForm({'email': user.email})
            if reset_form.is_valid():
                reset_form.save(
                    domain_override=domain_override,
                    subject_template_name=subject_template_name,
                    email_template_name=email_template_name,
                    use_https=use_https,
                    token_generator=token_generator,
                    from_email=from_email,
                    request=request,
                    html_email_template_name=html_email_template_name,
                    extra_email_context=extra_email_context,
                )


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'first_name', 'last_name', 'phone_number',
                 'address', 'profile_picture')

class PropertyOwnerRegistrationForm(forms.ModelForm):
    company_name = forms.CharField(
        required=True,
        help_text="Enter your company or business name",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Company Name'
        })
    )
    tax_id = forms.CharField(
        required=True,
        help_text="Enter your tax ID number for verification",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tax ID Number'
        })
    )

    class Meta:
        model = PropertyOwner
        fields = ('company_name', 'tax_id')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            'company_name',
            'tax_id'
        )

class TenantRegistrationForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ('emergency_contact', 'employment_info', 'id_proof')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.helper = FormHelper()
        self.helper.form_tag = False

class PropertyOwnerUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta:
        model = PropertyOwner
        fields = ('company_name', 'tax_id')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        if self.instance and self.instance.user:
            self.fields['email'].initial = self.instance.user.email
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name

class TenantUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta:
        model = Tenant
        fields = ('emergency_contact', 'employment_info','email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name

class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['name', 'type', 'description', 'price', 'duration_months',
                  'max_properties', 'max_units', 'is_active', 'stripe_price_id']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01'}),
            'duration_months': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'max_properties': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'max_units': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'stripe_price_id': forms.TextInput(attrs={'class': 'form-control'}),
        }

class UserLoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
    )

