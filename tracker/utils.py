from django.core.mail import send_mail
from django.conf import settings

def check_and_send_low_stock_alert(product):
    """
    Triggers an email alert if product quantity drops below reorder level.
    """
    if product.quantity <= product.reorder_level:
        subject = f"⚠️ Low Stock Alert: {product.name}"
        message = (
            f"Hello,\n\n"
            f"The stock level for '{product.name}' (SKU: {product.sku}) has fallen below its reorder threshold.\n\n"
            f"Current Quantity: {product.quantity}\n"
            f"Reorder Level: {product.reorder_level}\n\n"
            f"Please replenish the inventory soon."
        )
        recipient_list = [product.user.email] if product.user.email else ['admin@stocktracker.com']

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )