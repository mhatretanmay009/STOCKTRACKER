from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Product(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Selling Price (₹)")
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Cost Price / Purchase Price (₹)")
    image = models.ImageField(upload_to='product_images/', blank=True, null=True)
    reorder_level = models.PositiveIntegerField(default=5)
    warehouse_location = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_low_stock(self):
        """Returns True if quantity is at or below the reorder level."""
        return self.quantity <= self.reorder_level

    @property
    def total_stock_value(self):
        """Calculates total valuation based on selling price."""
        return self.quantity * self.unit_price

    @property
    def total_cost_value(self):
        """Calculates total cost incurred for current stock."""
        return self.quantity * self.cost_price

    @property
    def unit_profit_margin(self):
        """Calculates profit per unit in ₹."""
        return self.unit_price - self.cost_price

    @property
    def profit_margin_percentage(self):
        """Calculates profit margin percentage."""
        if self.cost_price > 0:
            return round(((self.unit_price - self.cost_price) / self.cost_price) * 100, 2)
        return 0.0

    def __str__(self):
        return f"{self.name} ({self.sku})"


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=200)
    action = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product_name} - {self.action}"


class Invoice(models.Model):
    INVOICE_TYPE_CHOICES = (
        ('IN', 'Inward (Stock Received / Purchase)'),
        ('OUT', 'Outward (Stock Delivered / Sales)'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=50, unique=True)
    transaction_type = models.CharField(max_length=3, choices=INVOICE_TYPE_CHOICES, default='OUT')
    party_name = models.CharField(max_length=200, help_text="Customer or Supplier Name")
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.invoice_number} - {self.party_name}"

    class Meta:
        ordering = ['-created_at']


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"


class Supplier(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.company_name or 'Individual'})"


class Customer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class CompanyProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='company_profile')
    company_name = models.CharField(max_length=200, default="My Business")
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    gstin_tax_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="GSTIN / Tax ID")
    logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)

    def __str__(self):
        return self.company_name

class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ('IN', 'Inward (Purchase)'),
        ('OUT', 'Outward (Sale)'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=3, choices=TRANSACTION_TYPES)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    party_name = models.CharField(max_length=200, blank=True, null=True, help_text="Supplier or Customer Name")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.total_amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.product.name} ({self.quantity})"

class Supplier(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.company_name


class Customer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


ROLE_CHOICES = (
    ('VIEWER', 'Viewer (Check Stock Only)'),
    ('SALES', 'Sales Agent (Invoicing & Customer Orders)'),
    ('CLERK', 'Stock Clerk (Inventory & Quantities)'),
    ('PURCHASER', 'Procurement (Suppliers & Reordering)'),
    ('ACCOUNTANT', 'Accountant (Financials & Reports)'),
    ('MANAGER', 'Store Manager (Full Operational Access)'),
    ('ADMIN', 'System Admin (User Approvals & Settings)'),
)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='VIEWER')
    requested_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CLERK')
    is_approved = models.BooleanField(default=False)

    # Granular Task Permissions
    can_add_product = models.BooleanField(default=False)
    can_create_bill = models.BooleanField(default=False)
    can_manage_suppliers = models.BooleanField(default=False)
    can_view_financials = models.BooleanField(default=False)
    can_export_reports = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Auto-configure permission flags based on assigned role
        if self.role == 'ADMIN' or self.role == 'MANAGER':
            self.can_add_product = True
            self.can_create_bill = True
            self.can_manage_suppliers = True
            self.can_view_financials = True
            self.can_export_reports = True
        elif self.role == 'CLERK':
            self.can_add_product = True
            self.can_create_bill = False
            self.can_manage_suppliers = False
            self.can_view_financials = False
            self.can_export_reports = False
        elif self.role == 'SALES':
            self.can_add_product = False
            self.can_create_bill = True
            self.can_manage_suppliers = False
            self.can_view_financials = False
            self.can_export_reports = False
        elif self.role == 'PURCHASER':
            self.can_add_product = True
            self.can_create_bill = False
            self.can_manage_suppliers = True
            self.can_view_financials = False
            self.can_export_reports = True
        elif self.role == 'ACCOUNTANT':
            self.can_add_product = False
            self.can_create_bill = False
            self.can_manage_suppliers = False
            self.can_view_financials = True
            self.can_export_reports = True
        elif self.role == 'VIEWER':
            self.can_add_product = False
            self.can_create_bill = False
            self.can_manage_suppliers = False
            self.can_view_financials = False
            self.can_export_reports = False

        # Superusers automatically receive full access
        if self.user.is_superuser:
            self.is_approved = True
            self.role = 'ADMIN'
            self.can_add_product = True
            self.can_create_bill = True
            self.can_manage_suppliers = True
            self.can_view_financials = True
            self.can_export_reports = True

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()} ({'Approved' if self.is_approved else 'Pending'})"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()