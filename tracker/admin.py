from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Profile, Product, ActivityLog, Invoice, Supplier, Customer

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
