import logging
import smtplib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.db import transaction

from .models import Notification, Wishlist


logger = logging.getLogger(__name__)
LOW_STOCK_THRESHOLD = 5


def _send_notification_email(notification_id):
    try:
        notification = Notification.objects.select_related('user').get(pk=notification_id)
    except Notification.DoesNotExist:
        logger.error("Notification %s disappeared before its email was sent.", notification_id)
        return

    if not notification.user.email:
        logger.warning("Cannot email notification %s: user has no email address.", notification_id)
        return

    frontend_url = getattr(settings, 'FRONTEND_URL', '').rstrip('/')
    link = f"{frontend_url}{notification.url}" if notification.url else frontend_url
    body = notification.message
    if link:
        body = f"{body}\n\nView in CraftGenius: {link}"

    try:
        sent_count = send_mail(
            subject=f"CraftGenius: {notification.title}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.user.email],
            fail_silently=False,
        )
    except (ImproperlyConfigured, OSError, smtplib.SMTPException):
        logger.exception("Email delivery failed for notification %s.", notification_id)
        return

    if sent_count != 1:
        logger.error("Email backend did not send notification %s.", notification_id)


def notify_user(user, notification_type, title, message, url=''):
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        url=url,
    )
    transaction.on_commit(lambda: _send_notification_email(notification.pk))
    return notification


def notify_product_stock_change(product, previous_stock):
    if previous_stock <= 0 < product.stock and product.is_active and product.is_approved:
        wishlists = Wishlist.objects.filter(product=product).select_related('user')
        for wishlist in wishlists:
            notify_user(
                wishlist.user,
                'RESTOCK',
                f"{product.name} is back in stock",
                f"The product on your wishlist, {product.name}, is available again.",
                url=f"/customer/product/{product.pk}",
            )

    entered_low_stock = (
        previous_stock > LOW_STOCK_THRESHOLD
        and product.stock <= LOW_STOCK_THRESHOLD
    )
    restocked_at_low_quantity = (
        previous_stock <= 0
        and 0 < product.stock <= LOW_STOCK_THRESHOLD
    )
    just_sold_out = previous_stock > 0 and product.stock == 0
    if entered_low_stock or restocked_at_low_quantity or just_sold_out:
        stock_message = (
            f"{product.name} is out of stock."
            if product.stock == 0
            else f"{product.name} is low on stock with {product.stock} unit(s) remaining."
        )
        notify_user(
            product.seller,
            'LOW_STOCK',
            "Low stock alert",
            stock_message,
            url="/handicrafter/products",
        )


def notify_order_placed(order):
    notify_user(
        order.customer,
        'ORDER',
        f"{order.product.name} placed",
        f"Your order for {order.product.name} has been received.",
        url="/customer/orders",
    )


def notify_payment_confirmed(order):
    notify_user(
        order.customer,
        'ORDER',
        f"{order.product.name} confirmed",
        f"Payment was confirmed for your order of {order.product.name}.",
        url="/customer/orders",
    )

    notify_seller_new_order(order)


def notify_seller_new_order(order):
    notify_user(
        order.seller,
        'NEW_ORDER',
        "New order received",
        f"{order.quantity} x {order.product.name}.",
        url="/handicrafter/orders",
    )


def notify_order_status(order):
    notify_user(
        order.customer,
        'ORDER',
        f"{order.product.name} updated",
        f"Your order for {order.product.name} is now {order.get_status_display().lower()}.",
        url="/customer/orders",
    )


def notify_refund(user, order, message, title="Refund update"):
    prefix = f"{order.product.name} - " if hasattr(order, 'product') and order.product else ""
    full_title = f"{prefix}{title}" if not title.startswith(prefix) else title
    notify_user(
        user,
        'REFUND',
        full_title,
        message,
        url="/customer/orders",
    )


def notify_product_approval(product, approved):
    decision = "approved" if approved else "not approved"
    notify_user(
        product.seller,
        'PRODUCT_APPROVAL',
        f"Product {decision}",
        f"Your product, {product.name}, was {decision}.",
        url="/handicrafter/products",
    )
