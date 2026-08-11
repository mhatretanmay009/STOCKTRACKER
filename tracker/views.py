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
    Customer, CompanyProfile, Transaction, Profile
)


def register_view(request):
    """Handles user registration with role selection and input validation guards."""
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
        profile, created = Profile.objects.get_or_create(user=user)

        profile.role = role
        profile.is_approved = user.is_superuser

        if role == 'SALES':
            profile.can_create_bill = True
        elif role == 'PURCHASER':
            profile.can_manage_suppliers = True
            profile.can_export_reports = True
        elif role == 'ACCOUNTANT':
            profile.can_export_reports = True
        elif role in ['ADMIN', 'MANAGER']:
            profile.can_create_bill = True
            profile.can_add_product = True
            profile.can_manage_suppliers = True
            profile.can_export_reports = True

        profile.save()

        login(request, user)
        messages.success(request, "Account created successfully!")
        return redirect('home')

    return render(request, 'registration/register.html')


@login_required
def home(request):
    """Main Inventory Dashboard displaying stock overview, charts, and product list."""
    profile = getattr(request.user, 'profile', None)

    if request.user.is_staff or request.user.is_superuser or (profile and profile.is_approved and profile.role in ['ADMIN', 'MANAGER']):
        products = Product.objects.all()
        recent_logs = ActivityLog.objects.all()[:5]
    else:
        products = Product.objects.filter(user=request.user)
        recent_logs = ActivityLog.objects.filter(user=request.user)[:5]

    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query) | Q(category__icontains=query)
        )

    total_items = products.count()
    total_quantity = sum(p.quantity for p in products)
    low_stock_count = sum(1 for p in products if p.is_low_stock)

    total_cost = sum(p.total_cost_value for p in products)
    total_valuation = sum(p.total_stock_value for p in products)
    total_potential_profit = total_valuation - total_cost

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
        'category_counts': category_counts,
        'query': query,
    }

    return render(request, 'home.html', context)


@login_required
def add_product(request):
    """Adds a new item to inventory with safe numeric input handling."""
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
            messages.error(request, "Invalid numeric value entered. Please check quantity and pricing fields.")
            return redirect('home')

        Product.objects.create(
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

        ActivityLog.objects.create(
            user=request.user,
            product_name=name,
            action=f"Added new product with stock of {quantity} units"
        )

        messages.success(request, f"Product '{name}' added successfully!")
        return redirect('home')


@login_required
def edit_product(request, product_id):
    """Edits an existing inventory item."""
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
    """Quick inline stock increment / decrement."""
    if request.user.is_staff or request.user.is_superuser:
        product = get_object_or_404(Product, id=product_id)
    else:
        product = get_object_or_404(Product, id=product_id, user=request.user)

    if action == 'increase':
        product.quantity += 1
        action_text = "Increased stock (+1)"
    elif action == 'decrease' and product.quantity > 0:
        product.quantity -= 1
        action_text = "Decreased stock (-1)"
    else:
        return redirect('home')

    product.save()

    ActivityLog.objects.create(
        user=request.user,
        product_name=product.name,
        action=action_text
    )

    return redirect('home')


@login_required
def delete_product(request, product_id):
    """Deletes an item from inventory."""
    if request.user.is_staff or request.user.is_superuser:
        product = get_object_or_404(Product, id=product_id)
    else:
        product = get_object_or_404(Product, id=product_id, user=request.user)

    if request.method == 'POST':
        product_name = product.name
        product.delete()

        ActivityLog.objects.create(
            user=request.user,
            product_name=product_name,
            action="Deleted item from inventory"
        )
        messages.success(request, f"Product '{product_name}' deleted.")
    return redirect('home')


@login_required
def create_transaction(request):
    """Creates sales (OUT) and purchase (IN) transactions with automated stock updates."""
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

                supplier = Supplier.objects.filter(name__iexact=party_name).first()
                if supplier:
                    supplier.total_supplied_value += total_amount
                    supplier.save()

            product.save()

            Transaction.objects.create(
                user=request.user,
                product=product,
                transaction_type=transaction_type,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                party_name=party_name,
                notes=notes
            )

            Invoice.objects.create(
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

    products = Product.objects.all() if (request.user.is_staff or request.user.is_superuser or (profile and profile.can_create_bill)) else Product.objects.filter(user=request.user)
    return render(request, 'transactions/create_transaction.html', {'products': products})


@login_required
def create_invoice(request):
    """Dynamic multi-item invoice generation."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_create_bill):
        messages.error(request, "Permission denied. You do not have access to generate invoices.")
        return redirect('home')

    if request.method == 'POST':
        transaction_type = request.POST.get('transaction_type')
        party_name = request.POST.get('party_name')
        contact_number = request.POST.get('contact_number')

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')

        if transaction_type == 'OUT':
            for pid, qty_str in zip(product_ids, quantities):
                if pid:
                    product = get_object_or_404(Product, id=pid)
                    qty = int(qty_str or 1)
                    if product.quantity < qty:
                        messages.error(request, f"Insufficient stock for '{product.name}'. Available: {product.quantity} units.")
                        return redirect('create_invoice')

        if product_ids:
            last_invoice = Invoice.objects.order_by('-id').first()
            invoice_id = (last_invoice.id + 1) if last_invoice else 1
            prefix = "INV-IN" if transaction_type == "IN" else "INV-OUT"
            invoice_number = f"{prefix}-{invoice_id:04d}"

            customer = Customer.objects.filter(name__iexact=party_name).first()

            invoice = Invoice.objects.create(
                user=request.user,
                customer=customer,
                invoice_number=invoice_number,
                transaction_type=transaction_type,
                party_name=party_name,
                contact_number=contact_number,
                total_amount=0
            )

            calculated_total = 0

            for pid, qty_str, price_str in zip(product_ids, quantities, unit_prices):
                if not pid:
                    continue
                qty = int(qty_str or 1)
                price = Decimal(price_str or '0.00')

                product = get_object_or_404(Product, id=pid)

                InvoiceItem.objects.create(
                    invoice=invoice,
                    product=product,
                    product_name=product.name,
                    quantity=qty,
                    unit_price=price
                )

                calculated_total += (qty * price)

                if transaction_type == 'IN':
                    product.quantity += qty
                    action_msg = f"Inward Bill ({invoice_number}): Added +{qty} stock"
                else:
                    product.quantity -= qty
                    action_msg = f"Outward Bill ({invoice_number}): Dispatched -{qty} stock"

                product.save()

                ActivityLog.objects.create(
                    user=request.user,
                    product_name=product.name,
                    action=action_msg
                )

            invoice.total_amount = calculated_total
            invoice.save()

            return redirect('invoice_detail', invoice_id=invoice.id)

    products = Product.objects.all() if (request.user.is_staff or request.user.is_superuser) else Product.objects.filter(user=request.user)
    return render(request, 'create_invoice.html', {'products': products})


@login_required
def invoice_detail(request, invoice_id):
    """Renders single invoice view."""
    invoice = get_object_or_404(Invoice, id=invoice_id)
    return render(request, 'invoice_detail.html', {'invoice': invoice})


@login_required
def invoice_list(request):
    """Lists invoices with search filter."""
    invoices = Invoice.objects.all() if (request.user.is_staff or request.user.is_superuser) else Invoice.objects.filter(user=request.user)

    query = request.GET.get('q', '').strip()
    if query:
        invoices = invoices.filter(
            Q(invoice_number__icontains=query) | Q(party_name__icontains=query)
        )

    return render(request, 'invoice_list.html', {'invoices': invoices, 'query': query})


@login_required
def invoice_history(request):
    """Lists past transactions."""
    transactions = Transaction.objects.all().order_by('-created_at') if (request.user.is_staff or request.user.is_superuser) else Transaction.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'transactions/invoice_history.html', {'transactions': transactions})


@login_required
def view_invoice(request, txn_id):
    """Printable invoice details view."""
    txn = get_object_or_404(Transaction, id=txn_id)
    profile = getattr(request.user, 'company_profile', None)
    return render(request, 'transactions/invoice_detail.html', {
        'txn': txn,
        'profile': profile
    })


@login_required
def supplier_list(request):
    """Lists suppliers and processes creation."""
    suppliers = Supplier.objects.all() if (request.user.is_staff or request.user.is_superuser) else Supplier.objects.filter(user=request.user)

    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        contact_person = request.POST.get('contact_person', '').strip()

        Supplier.objects.create(
            user=request.user,
            name=company_name or contact_person or "Unknown Supplier",
            company_name=company_name,
            contact_person=contact_person,
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            address=request.POST.get('address', '')
        )
        messages.success(request, "Supplier added successfully!")
        return redirect('supplier_list')

    return render(request, 'directory/suppliers.html', {'suppliers': suppliers})


@login_required
def delete_supplier(request, supplier_id):
    """Deletes a supplier record."""
    supplier = get_object_or_404(Supplier, id=supplier_id)
    supplier.delete()
    messages.success(request, "Supplier deleted.")
    return redirect('supplier_list')


@login_required
def customer_list(request):
    """Lists customers and processes creation."""
    customers = Customer.objects.all() if (request.user.is_staff or request.user.is_superuser) else Customer.objects.filter(user=request.user)

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
    """Deletes a customer record."""
    customer = get_object_or_404(Customer, id=customer_id)
    customer.delete()
    messages.success(request, "Customer deleted.")
    return redirect('customer_list')


@login_required
def company_settings(request):
    """Manages company branding, GSTIN, and profile info."""
    profile, created = CompanyProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        profile.company_name = request.POST.get('company_name', profile.company_name)
        profile.email = request.POST.get('email', profile.email)
        profile.phone = request.POST.get('phone', profile.phone)
        profile.address = request.POST.get('address', profile.address)
        profile.gstin_tax_id = request.POST.get('gstin_tax_id', profile.gstin_tax_id)

        if 'logo' in request.FILES:
            profile.logo = request.FILES['logo']

        profile.save()
        messages.success(request, "Company settings updated successfully!")
        return redirect('company_settings')

    return render(request, 'company_settings.html', {'profile': profile})


@login_required
def reports_view(request):
    """Renders the Reports & Export Dashboard page."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_export_reports):
        messages.error(request, "Permission denied. You do not have access to reports.")
        return redirect('home')

    recent_logs = ActivityLog.objects.filter(user=request.user).order_by('-timestamp')[:10]
    return render(request, 'reports.html', {'recent_logs': recent_logs})


@login_required
def export_csv(request):
    """Basic inventory CSV download."""
    products = Product.objects.all() if (request.user.is_staff or request.user.is_superuser) else Product.objects.filter(user=request.user)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Name', 'Category', 'Quantity', 'Unit Price', 'Location'])

    for p in products:
        writer.writerow([p.sku, p.name, p.category, p.quantity, p.unit_price, p.warehouse_location])

    return response


@login_required
def export_inventory_csv(request):
    """Generates and downloads CSV reports filtered by date range and report type."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_superuser and not (profile and profile.is_approved and profile.can_export_reports):
        messages.error(request, "Permission denied. You do not have access to export reports.")
        return redirect('home')

    report_type = request.GET.get('report_type', 'activity')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    filename = f"{report_type}_report_{start_date_str or 'all'}_to_{end_date_str or 'today'}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)

    if report_type == 'activity':
        logs = ActivityLog.objects.filter(user=request.user)
        if start_date_str:
            logs = logs.filter(timestamp__gte=datetime.strptime(start_date_str, '%Y-%m-%d'))
        if end_date_str:
            logs = logs.filter(timestamp__lte=datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

        writer.writerow(['Date & Time', 'Product Name', 'Action Executed', 'User'])
        for log in logs.order_by('-timestamp'):
            writer.writerow([log.timestamp.strftime('%Y-%m-%d %H:%M:%S'), log.product_name, log.action, log.user.username])

    elif report_type == 'products':
        products = Product.objects.filter(user=request.user)
        writer.writerow(['SKU', 'Name', 'Category', 'Quantity', 'Cost Price', 'Unit Price', 'Reorder Level', 'Warehouse Location'])
        for item in products:
            writer.writerow([item.sku, item.name, item.category, item.quantity, item.cost_price, item.unit_price, item.reorder_level, item.warehouse_location])

    elif report_type == 'invoices':
        invoices = Invoice.objects.filter(user=request.user)
        if start_date_str:
            invoices = invoices.filter(created_at__gte=datetime.strptime(start_date_str, '%Y-%m-%d'))
        if end_date_str:
            invoices = invoices.filter(created_at__lte=datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))

        writer.writerow(['Invoice ID', 'Date', 'Customer Name', 'Total Amount', 'Status'])
        for inv in invoices.order_by('-created_at'):
            writer.writerow([inv.id, inv.created_at.strftime('%Y-%m-%d %H:%M'), getattr(inv.customer, 'name', 'N/A'), getattr(inv, 'total_amount', 0.00), getattr(inv, 'status', 'Completed')])

    return response


@login_required
def export_low_stock_csv(request):
    """Exports low-stock alerts to CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="low_stock_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Product Name', 'Category', 'Quantity', 'Reorder Level', 'Warehouse Location'])

    products = Product.objects.all() if (request.user.is_staff or request.user.is_superuser) else Product.objects.filter(user=request.user)
    low_stock_products = [p for p in products if p.is_low_stock]

    for p in low_stock_products:
        writer.writerow([
            p.sku,
            p.name,
            p.category,
            p.quantity,
            p.reorder_level,
            p.warehouse_location or ''
        ])

    return response


@login_required
def print_inventory_report(request):
    """Renders printable inventory summary HTML."""
    products = Product.objects.all() if (request.user.is_staff or request.user.is_superuser) else Product.objects.filter(user=request.user)
    profile = getattr(request.user, 'company_profile', None)

    total_cost = sum(p.total_cost_value for p in products)
    total_valuation = sum(p.total_stock_value for p in products)

    context = {
        'products': products,
        'profile': profile,
        'total_cost': total_cost,
        'total_valuation': total_valuation,
        'total_profit': total_valuation - total_cost,
    }
    return render(request, 'reports/inventory_pdf.html', context)


@login_required
def supplier_portal(request):
    """Portal view for Suppliers."""
    try:
        supplier = request.user.supplier_profile
    except Supplier.DoesNotExist:
        messages.error(request, "Access denied. You do not have an active Supplier account.")
        return redirect('home')

    supplied_products = Product.objects.filter(warehouse_location__icontains=supplier.name)

    context = {
        'supplier': supplier,
        'supplied_products': supplied_products,
        'balance_payable': getattr(supplier, 'balance_payable', 0),
    }
    return render(request, 'supplier_portal.html', context)


@login_required
def customer_portal(request):
    """Portal view for Customers."""
    try:
        customer = request.user.customer_profile
        invoices = Invoice.objects.filter(customer=customer).order_by('-created_at')
    except Customer.DoesNotExist:
        invoices = Invoice.objects.filter(party_name__iexact=request.user.username).order_by('-created_at')
        customer = None

    context = {
        'customer': customer,
        'invoices': invoices,
        'balance_receivable': getattr(customer, 'balance_receivable', 0) if customer else 0,
    }
    return render(request, 'customer_portal.html', context)


def logout_view(request):
    """Logs out user and redirects to login."""
    logout(request)
    return redirect('login')
