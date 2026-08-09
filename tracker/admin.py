from django.contrib import admin
from .models import Product, ActivityLog, Profile

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'role',
        'requested_role',
        'is_approved',
        'can_add_product',
        'can_create_bill',
        'can_manage_suppliers',
        'can_view_financials',
        'can_export_reports'
    )
    list_filter = ('is_approved', 'role', 'requested_role')
    search_fields = ('user__username', 'user__email')
    list_editable = ('role', 'is_approved')
    actions = ['approve_users']

    @admin.action(description='Approve selected users with requested role')
    def approve_users(self, request, queryset):
        for profile in queryset:
            profile.is_approved = True
            profile.role = profile.requested_role
            profile.save()
        self.message_user(request, f"{queryset.count()} user(s) approved successfully.")

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'user', 'category', 'quantity', 'cost_price', 'unit_price')
    list_filter = ('category', 'user')
    search_fields = ('sku', 'name', 'user__username')

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'product_name', 'action', 'timestamp')
    list_filter = ('user', 'action')
    search_fields = ('product_name', 'user__username')
