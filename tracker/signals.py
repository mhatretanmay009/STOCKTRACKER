from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Product
from .utils import check_and_send_low_stock_alert

@receiver(post_save, sender=Product)
def check_low_stock(sender, instance, **kwargs):
    check_and_send_low_stock_alert(instance)