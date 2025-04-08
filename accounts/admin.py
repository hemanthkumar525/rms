from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, PropertyOwner, Tenant

class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'user_type', 'is_staff')
    list_filter = ('user_type', 'is_staff', 'is_active')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'address')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ('Additional info', {'fields': ('user_type', 'profile_picture')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'user_type'),
        }),
    )
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)

class PropertyOwnerAdmin(admin.ModelAdmin):
    list_display = ('user', 'company_name', 'verification_status')
    list_filter = ('verification_status',)
    search_fields = ('user__username', 'user__email', 'company_name')
    raw_id_fields = ('user',)

class TenantAdmin(admin.ModelAdmin):
    list_display = ('user', 'emergency_contact')
    search_fields = ('user__username', 'user__email', 'emergency_contact')
    raw_id_fields = ('user',)

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(PropertyOwner, PropertyOwnerAdmin)
admin.site.register(Tenant, TenantAdmin)
