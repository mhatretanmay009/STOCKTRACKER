from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Authentication
    path('register/', views.register_view, name='register'),
    path('signup/', views.register_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard & Inventory
    path('', views.home, name='home'),
    path('add-product/', views.add_product, name='add_product'),
    path('edit/<int:product_id>/', views.edit_product, name='edit_product'),
    path('delete-product/<int:product_id>/', views.delete_product, name='delete_product'),
    path('adjust/<int:product_id>/<str:action>/', views.adjust_stock, name='adjust_stock'),
    path('export-csv/', views.export_csv, name='export_csv'),

    # Billing & Transactions
    path('billing/new/', views.create_transaction, name='create_transaction'),
    path('billing/invoices/', views.invoice_history, name='invoice_history'),
    path('billing/invoice/<int:txn_id>/', views.view_invoice, name='view_invoice'),
    path('invoice/create/', views.create_invoice, name='create_invoice'),
    path('invoice/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/', views.invoice_list, name='invoice_list'),

    # Directories
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/delete/<int:supplier_id>/', views.delete_supplier, name='delete_supplier'),
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/delete/<int:customer_id>/', views.delete_customer, name='delete_customer'),

    # Reports & Settings
    path('settings/', views.company_settings, name='company_settings'),
    path('reports/', views.reports_view, name='reports'),
    path('export/csv/', views.export_inventory_csv, name='export_inventory_csv'),
    path('export/low-stock-csv/', views.export_low_stock_csv, name='export_low_stock_csv'),
    path('export/pdf-report/', views.print_inventory_report, name='print_inventory_report'),

    # Portals
    path('portal/supplier/', views.supplier_portal, name='supplier_portal'),
    path('portal/customer/', views.customer_portal, name='customer_portal'),
]
