from django.contrib import admin
from .models import Product, ActivityLog, Supplier, Customer, CompanyProfile, Transaction

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'category', 'quantity', 'cost_price', 'unit_price', 'reorder_level')
    search_fields = ('name', 'sku', 'category')
    list_filter = ('category',)

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'contact_person', 'phone', 'email', 'created_at')
    search_fields = ('company_name', 'contact_person', 'email', 'phone')

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'created_at')
    search_fields = ('name', 'email', 'phone')

@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'email', 'phone', 'gstin_tax_id')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'transaction_type', 'quantity', 'unit_price', 'total_amount', 'party_name', 'created_at')
    list_filter = ('transaction_type', 'created_at')

admin.site.register(ActivityLog)

