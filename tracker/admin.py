from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Profile, Product, ActivityLog, Invoice, Supplier, Customer
from .models import PasswordResetRequest

# 1. Embed Profile settings directly inside User pages
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile Settings'

class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)

# Unregister default User model and register customized UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# 2. Register all tracker models
admin.site.register(Profile)
admin.site.register(Product)
admin.site.register(ActivityLog)
admin.site.register(Invoice)
admin.site.register(Supplier)
admin.site.register(Customer)

@admin.register(PasswordResetRequest)
class PasswordResetRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_approved', 'is_used', 'created_at')
    list_editable = ('is_approved',)
    list_filter = ('is_approved', 'is_used', 'created_at')
    search_fields = ('user__username', 'user__email')