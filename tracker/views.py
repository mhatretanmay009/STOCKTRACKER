import json
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login , logout
from django.db.models import Q
from django.http import HttpResponse
from .models import Product, ActivityLog, Invoice, InvoiceItem, Supplier, Customer, CompanyProfile, Transaction, Profile
from .utils import check_and_send_low_stock_alert
from django.db.models import F, Sum, FloatField
from django.contrib import messages

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        requested_role = request.POST.get('requested_role', 'EMPLOYEE')
        if form.is_valid():
            user = form.save()
            # Update the auto-created profile with the requested role
            user.profile.requested_role = requested_role
            user.profile.save()
            messages.success(request, "Account created successfully! Please wait for Admin approval before accessing all features.")
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form})

@login_required
def home(request):
    if request.user.is_staff:
        products = Product.objects.all()
        recent_logs = ActivityLog.objects.all()[:5]
    else:
        products = Product.objects.filter(user=request.user)
        recent_logs = ActivityLog.objects.filter(user=request.user)[:5]

    # Search filter logic
    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(sku__icontains=query) | Q(category__icontains=query)
        )

    total_items = products.count()
    total_quantity = sum(p.quantity for p in products)
    low_stock_count = sum(1 for p in products if p.is_low_stock)

    # Financial Calculations
    total_cost = sum(p.total_cost_value for p in products)
    total_valuation = sum(p.total_stock_value for p in products)
    total_potential_profit = total_valuation - total_cost

    # Prepare data for Category Chart
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
    # Lock action if user is not approved or lacks permissions
    if not request.user.is_superuser and not (
            request.user.profile.is_approved and request.user.profile.can_add_product):
        messages.error(request, "Permission denied. You do not have rights to add products.")
        return redirect('home')

    if request.method == 'POST':
        sku = request.POST.get('sku')

        # 1. Check if SKU already exists to prevent crashes
        if Product.objects.filter(sku=sku).exists():
            messages.error(request, f"A product with SKU '{sku}' already exists.")
            return redirect('home')

        # 2. Create the product ONCE with all fields
        product = Product.objects.create(
            user=request.user,
            sku=sku,
            name=request.POST.get('name'),
            category=request.POST.get('category'),
            quantity=int(request.POST.get('quantity') or 0),
            cost_price=float(request.POST.get('cost_price') or 0.00),
            unit_price=float(request.POST.get('unit_price') or 0.00),
            reorder_level=int(request.POST.get('reorder_level') or 5),
            warehouse_location=request.POST.get('warehouse_location', ''),
            image=request.FILES.get('image')
        )

        # 3. Log the activity
        ActivityLog.objects.create(
            user=request.user,
            product_name=product.name,
            action="Added new item to inventory"
        )

        messages.success(request, f"Item '{product.name}' added successfully!")
        return redirect('home')

    return redirect('home')


@login_required
def edit_product(request, product_id):
    if request.user.is_staff:
        product = get_object_or_404(Product, id=product_id)
    else:
        product = get_object_or_404(Product, id=product_id, user=request.user)

    if request.method == 'POST':
        product.sku = request.POST.get('sku')
        product.name = request.POST.get('name')
        product.category = request.POST.get('category')
        product.quantity = int(request.POST.get('quantity', 0))
        product.unit_price = float(request.POST.get('unit_price', 0))
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
        return redirect('home')

    return render(request, 'edit_product.html', {'product': product})


@login_required
def adjust_stock(request, product_id, action):
    if request.user.is_staff:
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
    if request.user.is_staff:
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
    return redirect('home')


@login_required
def export_csv(request):
    if request.user.is_staff:
        products = Product.objects.all()
    else:
        products = Product.objects.filter(user=request.user)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Name', 'Category', 'Quantity', 'Unit Price', 'Location'])

    for p in products:
        writer.writerow([p.sku, p.name, p.category, p.quantity, p.unit_price, p.warehouse_location])

    return response

def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def create_invoice(request):
    if request.method == 'POST':
        transaction_type = request.POST.get('transaction_type')
        party_name = request.POST.get('party_name')
        contact_number = request.POST.get('contact_number')

        # Selected items data (arrays from dynamic form)
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')

        if product_ids:
            # Generate unique invoice number
            last_invoice = Invoice.objects.order_by('-id').first()
            invoice_id = (last_invoice.id + 1) if last_invoice else 1
            prefix = "INV-IN" if transaction_type == "IN" else "INV-OUT"
            invoice_number = f"{prefix}-{invoice_id:04d}"

            # Create Invoice record
            invoice = Invoice.objects.create(
                user=request.user,
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
                price = float(price_str or 0)

                product = get_object_or_404(Product, id=pid)

                # Save line item
                InvoiceItem.objects.create(
                    invoice=invoice,
                    product=product,
                    product_name=product.name,
                    quantity=qty,
                    unit_price=price
                )

                calculated_total += (qty * price)

                # Adjust inventory stock automatically
                if transaction_type == 'IN':
                    product.quantity += qty
                    action_msg = f"Inward Bill ({invoice_number}): Added +{qty} stock"
                else:
                    product.quantity = max(0, product.quantity - qty)
                    action_msg = f"Outward Bill ({invoice_number}): Dispatched -{qty} stock"

                product.save()
                # Check if stock dropped below reorder level
                check_and_send_low_stock_alert(product)

                # Record activity log
                ActivityLog.objects.create(
                    user=request.user,
                    product_name=product.name,
                    action=action_msg
                )

            invoice.total_amount = calculated_total
            invoice.save()

            return redirect('invoice_detail', invoice_id=invoice.id)

    # Fetch user's available products for dropdown selection
    products = Product.objects.all() if request.user.is_staff else Product.objects.filter(user=request.user)
    return render(request, 'create_invoice.html', {'products': products})

@login_required
def invoice_detail(request, invoice_id):
    if request.user.is_staff:
        invoice = get_object_or_404(Invoice, id=invoice_id)
    else:
        invoice = get_object_or_404(Invoice, id=invoice_id, user=request.user)

    return render(request, 'invoice_detail.html', {'invoice': invoice})

@login_required
def invoice_list(request):
    if request.user.is_staff:
        invoices = Invoice.objects.all()
    else:
        invoices = Invoice.objects.filter(user=request.user)

    # Search filter
    query = request.GET.get('q', '').strip()
    if query:
        invoices = invoices.filter(
            Q(invoice_number__icontains=query) | Q(party_name__icontains=query)
        )

    return render(request, 'invoice_list.html', {'invoices': invoices, 'query': query})


@login_required
def supplier_list(request):
    if request.method == 'POST':
        Supplier.objects.create(
            user=request.user,
            name=request.POST.get('name'),
            company_name=request.POST.get('company_name'),
            email=request.POST.get('email'),
            phone=request.POST.get('phone'),
            address=request.POST.get('address')
        )
        return redirect('supplier_list')

    suppliers = Supplier.objects.all() if request.user.is_staff else Supplier.objects.filter(user=request.user)
    return render(request, 'suppliers.html', {'suppliers': suppliers})


@login_required
def customer_list(request):
    if request.method == 'POST':
        Customer.objects.create(
            user=request.user,
            name=request.POST.get('name'),
            email=request.POST.get('email'),
            phone=request.POST.get('phone'),
            address=request.POST.get('address')
        )
        return redirect('customer_list')

    customers = Customer.objects.all() if request.user.is_staff else Customer.objects.filter(user=request.user)
    return render(request, 'customers.html', {'customers': customers})

# Helper to check if user is an Admin/Manager
def is_admin_user(user):
    return user.is_staff or user.is_superuser

@login_required
def company_settings(request):
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
def export_inventory_csv(request):
    """Exports all inventory items to a CSV file."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="inventory_report.csv"'

    writer = csv.writer(response)
    # Header row
    writer.writerow([
        'SKU', 'Product Name', 'Category', 'Quantity',
        'Cost Price (₹)', 'Selling Price (₹)', 'Total Valuation (₹)',
        'Reorder Level', 'Warehouse Location'
    ])

    products = Product.objects.all() if request.user.is_staff else Product.objects.filter(user=request.user)

    for p in products:
        writer.writerow([
            p.sku,
            p.name,
            p.category,
            p.quantity,
            p.cost_price,
            p.unit_price,
            p.total_stock_value,
            p.reorder_level,
            p.warehouse_location or ''
        ])

    return response


@login_required
def export_low_stock_csv(request):
    """Exports only low-stock items to a CSV file."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="low_stock_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Product Name', 'Category', 'Quantity', 'Reorder Level', 'Warehouse Location'])

    products = Product.objects.all() if request.user.is_staff else Product.objects.filter(user=request.user)
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
    """Renders a print-ready clean HTML report for PDF export/printing."""
    products = Product.objects.all() if request.user.is_staff else Product.objects.filter(user=request.user)
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
def create_transaction(request):
    """Handles stock entry (Inward) and exit (Outward)."""
    products = Product.objects.all() if request.user.is_staff else Product.objects.filter(user=request.user)

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        transaction_type = request.POST.get('transaction_type')
        quantity = int(request.POST.get('quantity', 0))
        unit_price = float(request.POST.get('unit_price', 0))
        party_name = request.POST.get('party_name', '')
        notes = request.POST.get('notes', '')

        product = get_object_or_404(Product, id=product_id)

        # Validate stock availability for sales
        if transaction_type == 'OUT' and product.quantity < quantity:
            messages.error(request, f"Insufficient stock! Available: {product.quantity}")
            return redirect('create_transaction')

        # Create Transaction Record
        txn = Transaction.objects.create(
            user=request.user,
            product=product,
            transaction_type=transaction_type,
            quantity=quantity,
            unit_price=unit_price,
            party_name=party_name,
            notes=notes
        )

        # Update Inventory Quantity
        if transaction_type == 'IN':
            product.quantity += quantity
        else:
            product.quantity -= quantity
        product.save()

        messages.success(request, f"Transaction recorded! Invoice #{txn.id} created.")
        return redirect('view_invoice', txn_id=txn.id)

    return render(request, 'transactions/create_transaction.html', {'products': products})


@login_required
def invoice_history(request):
    """Lists all past transactions/invoices."""
    transactions = Transaction.objects.all().order_by('-created_at') if request.user.is_staff else Transaction.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'transactions/invoice_history.html', {'transactions': transactions})


@login_required
def view_invoice(request, txn_id):
    """Renders a printable invoice for a specific transaction."""
    transaction = get_object_or_404(Transaction, id=txn_id)
    profile = getattr(request.user, 'company_profile', None)
    return render(request, 'transactions/invoice_detail.html', {
        'txn': transaction,
        'profile': profile
    })

# --- SUPPLIER VIEWS ---
@login_required
def supplier_list(request):
    suppliers = Supplier.objects.filter(user=request.user) if not request.user.is_staff else Supplier.objects.all()

    if request.method == 'POST':
        Supplier.objects.create(
            user=request.user,
            company_name=request.POST.get('company_name'),
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
    if request.user.is_staff or supplier.user == request.user:
        supplier.delete()
        messages.success(request, "Supplier deleted.")
    return redirect('supplier_list')


# --- CUSTOMER VIEWS ---
@login_required
def customer_list(request):
    customers = Customer.objects.filter(user=request.user) if not request.user.is_staff else Customer.objects.all()

    if request.method == 'POST':
        Customer.objects.create(
            user=request.user,
            name=request.POST.get('name'),
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
    if request.user.is_staff or customer.user == request.user:
        customer.delete()
        messages.success(request, "Customer deleted.")
    return redirect('customer_list')

