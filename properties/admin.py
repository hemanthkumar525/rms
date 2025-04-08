from django.contrib import admin
from .models import *

class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 1

class LeaseAgreementInline(admin.TabularInline):
    model = LeaseAgreement
    extra = 0
    show_change_link = True

class PropertyAdmin(admin.ModelAdmin):
    list_display = ['title', 'property_type', 'city', 'owner', 'created_at']
    list_filter = ['property_type', 'city', 'created_at']
    search_fields = ['title', 'address', 'city']
    inlines = [PropertyImageInline, LeaseAgreementInline]
    raw_id_fields = ('owner',)


class PropertyUnitAdmin(admin.ModelAdmin):
    list_display = ['property', 'unit_number', 'monthly_rent', 'bedrooms', 'is_available']
    list_filter = ['is_available', 'bedrooms']
    search_fields = ['property__title', 'unit_number']

class LeaseAgreementAdmin(admin.ModelAdmin):
    list_display = ('property', 'tenant', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'start_date')
    search_fields = ('property__title', 'tenant__user__username')
    raw_id_fields = ('property', 'tenant')
    date_hierarchy = 'start_date'

class PropertyMaintenanceAdmin(admin.ModelAdmin):
    list_display = ('title', 'property', 'reported_by', 'status', 'priority', 'reported_date')
    list_filter = ('status', 'priority', 'reported_date')
    search_fields = ('title', 'description', 'property__title')
    raw_id_fields = ('property', 'reported_by')
    date_hierarchy = 'reported_date'

class BankAccountAdmin(admin.ModelAdmin):
    list_display = ('title', 'account_type', 'status', 'account_mode', 'property')
    list_filter = ('status', 'account_type', 'account_mode')
    search_fields = ('title', 'property__title')

admin.site.register(Property, PropertyAdmin)
admin.site.register(LeaseAgreement, LeaseAgreementAdmin)
admin.site.register(PropertyMaintenance, PropertyMaintenanceAdmin)
admin.site.register(PropertyUnit, PropertyUnitAdmin)
admin.site.register(BankAccount, BankAccountAdmin)
