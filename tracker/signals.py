from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from .models import Product

@receiver(post_save, sender=Product)
def check_low_stock(sender, instance, **kwargs):
    threshold = 10  # Define low stock limit
    if instance.quantity <= threshold:
        send_mail(
            subject=f"Low Stock Warning: {instance.name}",
            message=(
                f"Stock alert for '{instance.name}' (SKU: {instance.sku}).\n"
                f"Current Quantity: {instance.quantity}\n"
                f"Location: {instance.warehouse_location}"
            ),
            from_email='noreply@stocktracker.com',
            recipient_list=['manager@example.com'],  # Replace with target email
            fail_silently=True,
        )