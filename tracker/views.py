import csv
from datetime import datetime
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import login, logout
from django.db.models import Q
from django.db import transaction
from django.http import HttpResponse
from django.contrib import messages

from .models import (
    Product, ActivityLog, Invoice, InvoiceItem, Supplier,
    Customer, CompanyProfile, Transaction, Profile, PasswordResetRequest
)
from .utils import check_and_send_low_stock_alert


# --- HELPER PERMISSION CHECKS ---

def is_internal_staff(user):
    """Verifies that the user is an active, approved internal company staff member."""
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, 'profile', None)
    if not profile or not profile.is_approved:
        return False
    role_str = (profile.role or '').upper()
    return not ('SUPPLIER' in role_str or 'CUSTOMER' in role_str)


# --- AUTHENTICATION & REGISTRATION ---

def register_view(request):
    """User registration with default permission assignment."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        role = request.POST.get('role', 'VIEWER')

        if not username:
            messages.error(request, "Username is required.")
            return redirect('register')

        if not password:
            messages.error(request, "Password is required.")
            return redirect('register')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
            return redirect('register')

        user = User.objects.create_user(username=username, email=email, password=password)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = role
        profile.requested_role = role
        profile.is_approved = user.is_superuser
        profile.save()

        login(request, user)
        messages.success(request, "Account created successfully!")
        return redirect('home')

    return render(request, 'registration/register.html')


# --- DASHBOARD & INVENTORY ---

@login_required
def home(request):
    """Central Dashboard: displays shared stock to all approved internal roles."""
    profile = getattr(request.user, 'profile', None)
    role_str = (getattr(profile, 'role', '') or '').upper()

    # Route external accounts directly to dedicated portals
    if 'SUPPLIER' in role_str:
        return redirect('supplier_portal')
    if 'CUSTOMER' in role_str:
        return redirect('customer_portal')

    # Pending approval check
    if not request.user.is_superuser and not getattr(profile, 'is_approved', False):
        return render(request, 'home.html', {
            'pending_approval': True,
            'products': [],
            'recent_logs': [],
            'total_items': 0,
            'total_quantity': 0,
            'low_stock_count': 0,
            'can_view_financials': False,
        })

    # All approved internal team members share central warehouse inventory
    if is_internal_staff(request.user):
        products = Product.objects.all()
        recent_logs = ActivityLog.objects.all().order_by('-timestamp')[:5]
    else:
        products = Product.objects.filter(user=request.user)
        recent_logs = ActivityLog.objects.filter(user=request.user).order_by('-timestamp')[:5]

    # Search filter logic
    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query) | Q(category__icontains=query)
        )

    total_items = products.count()
    total_quantity = sum(p.quantity for p in products)
    low_stock_count = sum(1 for p in products if p.is_low_stock)

    # Protect financial metrics: accessible to Superusers, Admins, Managers, and Accountants
    can_view_fin = request.user.is_superuser or getattr(profile, 'can_view_financials', False)
    if can_view_fin:
        total_cost = sum(p.total_cost_value for p in products)
        total_valuation = sum(p.total_stock_value for p in products)
        total_potential_profit = total_valuation - total_cost
    else:
        total_cost = None
        total_valuation = None
        total_potential_profit = None

    # Chart Category Breakdown
    category_counts = {}
    for p in products:
        cat = p.category.strip() if p.category and p.category.strip() else 'Uncategorized'
        category_counts[cat] = category_counts.get(cat, 0) + p.quantity

    context = {
        'products': products,
        'recent_logs': recent_logs,
        'total_items': total_items,
        'total_quantity': total_quantity,
        'low_stock_count': low_stock_count,
        'total_cost': total_cost,
        'total_valuation': total_valuation,
        'total_potential_profit': total_potential_profit,
        'can_view_financials': can_view_fin,
        'category_counts': category_counts,
        'query': query,
        'profile': profile,
        'pending_approval': False,
    }
    return render(request, 'home.html', context)


@login_required
def add_product(request):
    """Authorized for Superusers, Admins, Managers, Stock Clerks, and Procurement."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_add_product):
        messages.error(request, "Permission denied. You do not have access to add products.")
        return redirect('home')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        sku = request.POST.get('sku', '').strip()
        category = request.POST.get('category', '').strip()

        raw_quantity = request.POST.get('quantity') or '0'
        raw_cost_price = request.POST.get('cost_price') or '0.00'
        raw_unit_price = request.POST.get('unit_price') or '0.00'
        raw_reorder_level = request.POST.get('reorder_level') or '5'

        try:
            quantity = int(raw_quantity)
            cost_price = Decimal(raw_cost_price)
            unit_price = Decimal(raw_unit_price)
            reorder_level = int(raw_reorder_level)
        except (ValueError, TypeError):
            messages.error(request, "Invalid numeric input. Please check quantity and pricing.")
            return redirect('home')

        product = Product(
            user=request.user,
            sku=sku,
            name=name,
            category=category,
            quantity=quantity,
            cost_price=cost_price,
            unit_price=unit_price,
            reorder_level=reorder_level,
            warehouse_location=request.POST.get('warehouse_location', '')
        )

        if request.FILES.get('image'):
            product.image = request.FILES.get('image')

        product.save()

        ActivityLog.objects.create(
            user=request.user,
            product_name=name,
            action=f"Added new product with {quantity} units"
        )
        messages.success(request, f"Product '{name}' added successfully!")
        return redirect('home')

    return redirect('home')


@login_required
def edit_product(request, product_id):
    """Authorized for Superusers, Admins, Managers, Stock Clerks, and Procurement."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_add_product):
        messages.error(request, "Permission denied. You cannot edit products.")
        return redirect('home')

    product = get_object_or_404(Product, id=product_id)

    if request.method == 'POST':
        product.sku = request.POST.get('sku')
        product.name = request.POST.get('name')
        product.category = request.POST.get('category')
        product.quantity = int(request.POST.get('quantity', 0))
        product.cost_price = Decimal(request.POST.get('cost_price', '0.00'))
        product.unit_price = Decimal(request.POST.get('unit_price', '0.00'))
        product.reorder_level = int(request.POST.get('reorder_level', 5))
        product.warehouse_location = request.POST.get('warehouse_location')

        if request.FILES.get('image'):
            product.image = request.FILES.get('image')

        product.save()

        ActivityLog.objects.create(
            user=request.user,
            product_name=product.name,
            action="Updated product details"
        )
        messages.success(request, f"Product '{product.name}' updated successfully.")
        return redirect('home')

    return render(request, 'edit_product.html', {'product': product})


@login_required
def adjust_stock(request, product_id, action):
    """Quick stock adjustments for Admins, Managers, and Stock Clerks."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_add_product):
        messages.error(request, "Permission denied. You cannot adjust stock.")
        return redirect('home')

    product = get_object_or_404(Product, id=product_id)

    if action == 'increase':
        product.quantity += 1
        action_text = "Increased stock (+1)"
    elif action == 'decrease' and product.quantity > 0:
        product.quantity -= 1
        action_text = "Decreased stock (-1)"
    else:
        return redirect('home')

    product.save()
    ActivityLog.objects.create(user=request.user, product_name=product.name, action=action_text)
    return redirect('home')


@login_required
def delete_product(request, product_id):
    """Deletion reserved for Admins and Managers."""
    profile = getattr(request.user, 'profile', None)
    role_str = (getattr(profile, 'role', '') or '').upper()
    is_authorized = request.user.is_superuser or ('ADMIN' in role_str or 'MANAGER' in role_str)

    if not is_authorized:
        messages.error(request, "Permission denied. Only Admins and Managers can delete items.")
        return redirect('home')

    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        name = product.name
        product.delete()
        ActivityLog.objects.create(user=request.user, product_name=name, action="Deleted item from inventory")
        messages.success(request, f"Product '{name}' deleted.")
    return redirect('home')


# --- BILLING & TRANSACTIONS ---

@login_required
def create_transaction(request):
    """Authorized for Superusers, Admins, Managers, Sales Agents, and Procurement."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_create_bill):
        messages.error(request, "Permission denied. You do not have access to create transactions.")
        return redirect('home')

    if request.method == 'POST':
        transaction_type = request.POST.get('transaction_type')
        product_id = request.POST.get('product_id')
        party_name = request.POST.get('party_name', '').strip()
        notes = request.POST.get('notes', '')

        raw_quantity = request.POST.get('quantity') or '0'
        raw_unit_price = request.POST.get('unit_price') or '0.00'

        try:
            quantity = int(raw_quantity)
            unit_price = Decimal(raw_unit_price)
        except (ValueError, TypeError):
            messages.error(request, "Please enter valid numbers for quantity and unit price.")
            return redirect('create_transaction')

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect('create_transaction')

        product = get_object_or_404(Product, id=product_id)
        total_amount = quantity * unit_price

        with transaction.atomic():
            if transaction_type == 'OUT':
                if product.quantity < quantity:
                    messages.error(
                        request,
                        f"Insufficient stock for '{product.name}'. Available: {product.quantity} units."
                    )
                    return redirect('create_transaction')

                product.quantity -= quantity
                action_text = f"Sold {quantity} units to {party_name} @ ₹{unit_price}/unit"

                customer = Customer.objects.filter(name__iexact=party_name).first()
                if customer:
                    customer.total_purchased_value += total_amount
                    customer.save()

            elif transaction_type == 'IN':
                product.quantity += quantity
                action_text = f"Purchased {quantity} units from {party_name} @ ₹{unit_price}/unit"

                supplier = Supplier.objects.filter(
                    Q(company_name__iexact=party_name) | Q(name__iexact=party_name)
                ).first()
                if supplier:
                    supplier.total_supplied_value += total_amount
                    supplier.save()

            product.save()

            Transaction.objects.create(
                user=request.user,
                party_name=party_name,
                transaction_type=transaction_type,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                notes=notes
            )

            ActivityLog.objects.create(
                user=request.user,
                product_name=product.name,
                action=action_text
            )

        messages.success(request, "Transaction recorded successfully!")
        return redirect('invoice_history')

    products = Product.objects.all()
    return render(request, 'transactions/create_transaction.html', {'products': products})


@login_required
def invoice_history(request):
    """Displays transaction history to all approved internal staff."""
    if not is_internal_staff(request.user):
        messages.error(request, "Access restricted.")
        return redirect('home')

    transactions = Transaction.objects.all().order_by('-created_at')
    return render(request, 'transactions/invoice_history.html', {'transactions': transactions})


@login_required
def view_invoice(request, txn_id):
    """Printable invoice details."""
    txn = get_object_or_404(Transaction, id=txn_id)
    profile = getattr(request.user, 'company_profile', None)
    return render(request, 'transactions/invoice_detail.html', {'txn': txn, 'profile': profile})


@login_required
def create_invoice(request):
    """Multi-item invoice creation view."""
    products = Product.objects.all()
    return render(request, 'create_invoice.html', {'products': products})


@login_required
def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    return render(request, 'invoice_detail.html', {'invoice': invoice})


@login_required
def invoice_list(request):
    invoices = Invoice.objects.all().order_by('-created_at')
    return render(request, 'invoice_list.html', {'invoices': invoices})


# --- SUPPLIER & CUSTOMER DIRECTORY ---

@login_required
def supplier_list(request):
    """Accessible to Superusers, Admins, Managers, and Procurement."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_manage_suppliers):
        messages.error(request, "Permission denied. You cannot manage suppliers.")
        return redirect('home')

    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        Supplier.objects.create(
            user=request.user,
            name=request.POST.get('contact_person', ''),
            company_name=request.POST.get('company_name', ''),
            contact_person=request.POST.get('contact_person', ''),
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            address=request.POST.get('address', '')
        )
        messages.success(request, "Supplier added successfully!")
        return redirect('supplier_list')

    return render(request, 'directory/suppliers.html', {'suppliers': suppliers})


@login_required
def delete_supplier(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id)
    supplier.delete()
    messages.success(request, "Supplier deleted.")
    return redirect('supplier_list')


@login_required
def customer_list(request):
    """Accessible to Superusers, Admins, Managers, and Sales Agents."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and (profile.can_create_bill or profile.can_manage_suppliers)):
        messages.error(request, "Permission denied. You cannot view customer records.")
        return redirect('home')

    customers = Customer.objects.all()

    if request.method == 'POST':
        Customer.objects.create(
            user=request.user,
            name=request.POST.get('name', ''),
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            address=request.POST.get('address', '')
        )
        messages.success(request, "Customer added successfully!")
        return redirect('customer_list')

    return render(request, 'directory/customers.html', {'customers': customers})


@login_required
def delete_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    customer.delete()
    messages.success(request, "Customer deleted.")
    return redirect('customer_list')


# --- REPORTS & FINANCIAL EXPORTS ---

@login_required
def export_csv(request):
    """Basic inventory CSV download (resolves urls.py route)."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_export_reports):
        messages.error(request, "Permission denied.")
        return redirect('home')

    products = Product.objects.all()
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_catalog.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Name', 'Category', 'Quantity', 'Unit Price', 'Location'])

    for p in products:
        writer.writerow([p.sku, p.name, p.category, p.quantity, p.unit_price, p.warehouse_location or ''])

    return response


@login_required
def reports_view(request):
    """Accessible to Superusers, Admins, Managers, and Accountants."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_export_reports):
        messages.error(request, "Permission denied. You do not have access to reports.")
        return redirect('home')

    recent_logs = ActivityLog.objects.all().order_by('-timestamp')[:15]
    return render(request, 'reports.html', {'recent_logs': recent_logs})


@login_required
def export_inventory_csv(request):
    """Date-filtered CSV export for authorized report viewers."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_export_reports):
        messages.error(request, "Permission denied.")
        return redirect('home')

    report_type = request.GET.get('report_type', 'activity')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    filename = f"{report_type}_report_{start_date_str or 'all'}_to_{end_date_str or 'today'}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)

    if report_type == 'activity':
        logs = ActivityLog.objects.all()
        if start_date_str:
            logs = logs.filter(timestamp__gte=datetime.strptime(start_date_str, '%Y-%m-%d'))
        if end_date_str:
            logs = logs.filter(timestamp__lte=datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

        writer.writerow(['Date & Time', 'Product Name', 'Action Executed', 'User'])
        for log in logs.order_by('-timestamp'):
            writer.writerow([log.timestamp.strftime('%Y-%m-%d %H:%M:%S'), log.product_name, log.action, log.user.username])

    elif report_type == 'products':
        products = Product.objects.all()
        writer.writerow(['SKU', 'Name', 'Category', 'Quantity', 'Cost Price', 'Unit Price', 'Reorder Level', 'Warehouse Location'])
        for item in products:
            writer.writerow([item.sku, item.name, item.category, item.quantity, item.cost_price, item.unit_price, item.reorder_level, item.warehouse_location or ''])

    return response


@login_required
def export_low_stock_csv(request):
    """Low stock report download."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_export_reports):
        messages.error(request, "Permission denied.")
        return redirect('home')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="low_stock_report.csv"'
    writer = csv.writer(response)
    writer.writerow(['SKU', 'Product Name', 'Category', 'Quantity', 'Reorder Level', 'Warehouse Location'])

    for p in [item for item in Product.objects.all() if item.is_low_stock]:
        writer.writerow([p.sku, p.name, p.category, p.quantity, p.reorder_level, p.warehouse_location or ''])

    return response


@login_required
def print_inventory_report(request):
    """Printable audit report showing complete financial totals."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_view_financials):
        messages.error(request, "Permission denied. Financial data access is restricted.")
        return redirect('home')

    products = Product.objects.all()
    comp_profile = getattr(request.user, 'company_profile', None)
    total_cost = sum(p.total_cost_value for p in products)
    total_valuation = sum(p.total_stock_value for p in products)

    return render(request, 'reports/inventory_pdf.html', {
        'products': products,
        'profile': comp_profile,
        'total_cost': total_cost,
        'total_valuation': total_valuation,
        'total_profit': total_valuation - total_cost,
    })


# --- SETTINGS & PORTALS ---

@login_required
def company_settings(request):
    """Only Admins and Managers can edit business details & branding."""
    profile = getattr(request.user, 'profile', None)
    role_str = (getattr(profile, 'role', '') or '').upper()
    if not request.user.is_superuser and not ('ADMIN' in role_str or 'MANAGER' in role_str):
        messages.error(request, "Permission denied. Only Admins and Managers can update company settings.")
        return redirect('home')

    comp_profile, _ = CompanyProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        comp_profile.company_name = request.POST.get('company_name', comp_profile.company_name)
        comp_profile.email = request.POST.get('email', comp_profile.email)
        comp_profile.phone = request.POST.get('phone', comp_profile.phone)
        comp_profile.address = request.POST.get('address', comp_profile.address)
        comp_profile.gstin_tax_id = request.POST.get('gstin_tax_id', comp_profile.gstin_tax_id)

        if 'logo' in request.FILES:
            comp_profile.logo = request.FILES['logo']

        comp_profile.save()
        messages.success(request, "Company settings updated successfully!")
        return redirect('company_settings')

    return render(request, 'company_settings.html', {'profile': comp_profile})


@login_required
def supplier_portal(request):
    try:
        supplier = Supplier.objects.filter(user=request.user).first()
    except Exception:
        supplier = None

    supplied_products = Product.objects.filter(
        warehouse_location__icontains=getattr(supplier, 'company_name', '')
    ) if supplier else []

    return render(request, 'supplier_portal.html', {
        'supplier': supplier,
        'supplied_products': supplied_products,
        'balance_payable': getattr(supplier, 'balance_payable', 0),
    })


@login_required
def customer_portal(request):
    customer = Customer.objects.filter(user=request.user).first()
    invoices = Invoice.objects.filter(party_name=getattr(customer, 'name', '')) if customer else []

    return render(request, 'customer_portal.html', {
        'customer': customer,
        'invoices': invoices,
        'balance_receivable': getattr(customer, 'balance_receivable', 0),
    })


# --- ADMIN-APPROVED PASSWORD RESET ---

def forgot_password_request(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        try:
            target_user = User.objects.get(username=username)
        except User.DoesNotExist:
            messages.error(request, "No account found with that username.")
            return render(request, 'registration/forgot_password_request.html')

        existing_request = PasswordResetRequest.objects.filter(
            user=target_user, is_used=False
        ).order_by('-created_at').first()

        if existing_request:
            if existing_request.is_approved:
                return redirect('set_new_password', token=existing_request.token)
            messages.warning(request, "Your request is pending approval from an Admin or Manager.")
            return render(request, 'registration/forgot_password_request.html')

        PasswordResetRequest.objects.create(user=target_user, is_approved=False)
        messages.success(request, "Reset request submitted. Once approved by an Admin, return here to set your password.")
        return render(request, 'registration/forgot_password_request.html')

    return render(request, 'registration/forgot_password_request.html')


def set_new_password(request, token):
    reset_req = get_object_or_404(PasswordResetRequest, token=token, is_approved=True, is_used=False)

    if request.method == 'POST':
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if not password or not confirm_password:
            messages.error(request, "Please enter all fields.")
            return render(request, 'registration/set_new_password.html', {'reset_req': reset_req})

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'registration/set_new_password.html', {'reset_req': reset_req})

        user = reset_req.user
        user.set_password(password)
        user.save()

        reset_req.is_used = True
        reset_req.save()

        messages.success(request, "Password updated successfully! You can now log in.")
        return redirect('login')

    return render(request, 'registration/set_new_password.html', {'reset_req': reset_req})


def logout_view(request):
    logout(request)
    return redirect('login')
