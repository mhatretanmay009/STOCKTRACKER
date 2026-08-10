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
    TRANSACTION_TYPES = (
        ('IN', 'Inward (Purchase)'),
        ('OUT', 'Outward (Sale)'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    party_name = models.CharField(max_length=200)
    transaction_type = models.CharField(max_length=3, choices=TRANSACTION_TYPES, default='OUT')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_transaction_type_display()} - #{self.id} ({self.party_name})"


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField(default=0)
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
    ('SUPPLIER', 'External Supplier Portal'),
    ('CUSTOMER', 'External Customer Portal'),
)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='VIEWER')
    requested_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CLERK')
    is_approved = models.BooleanField(default=False)

    # Permission Flags
    can_add_product = models.BooleanField(default=False)
    can_create_bill = models.BooleanField(default=False)
    can_manage_suppliers = models.BooleanField(default=False)
    can_view_financials = models.BooleanField(default=False)
    can_export_reports = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Auto-assign permissions based on assigned role
        if self.role in ['ADMIN', 'MANAGER']:
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

        # Superuser Overrides
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


class Supplier(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_profile')
    name = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    address = models.TextField(blank=True, default='')

    total_supplied_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_paid_to_supplier = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    @property
    def balance_payable(self):
        return self.total_supplied_value - self.total_paid_to_supplier

    def __str__(self):
        return f"{self.name} ({self.company_name})"


class Customer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='customer_profile')
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    address = models.TextField(blank=True, default='')

    total_purchased_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_paid_by_customer = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    @property
    def balance_receivable(self):
        return self.total_purchased_value - self.total_paid_by_customer

    def __str__(self):
        return self.name
