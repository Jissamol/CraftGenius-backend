from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='products'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products'
    )
    name = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock = models.PositiveIntegerField(default=0)
    tags = models.CharField(max_length=500, blank=True, default='')
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def primary_image(self):
        img = self.images.filter(is_primary=True).first()
        if not img:
            img = self.images.first()
        return img

    @property
    def average_rating(self):
        reviews = self.reviews.all()
        if reviews.exists():
            return round(reviews.aggregate(models.Avg('rating'))['rating__avg'], 1)
        return 0

    @property
    def total_orders(self):
        return self.orders.count()


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='products/')
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.name}"


class Order(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
        ('FAILED', 'Failed Payment'),
        ('REFUNDED', 'Refunded'),
        ('RETURN_REQUESTED', 'Return Requested'),
        ('RETURNED', 'Returned'),
        ('DISPUTED', 'Disputed'),
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_orders'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='seller_orders'
    )
    quantity = models.PositiveIntegerField(default=1)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    is_paid = models.BooleanField(default=False)
    stripe_session_id = models.CharField(max_length=255, blank=True, default='')
    stripe_payment_intent = models.CharField(max_length=255, blank=True, default='')
    tracking_number = models.CharField(max_length=100, blank=True, default='')
    cancellation_reason = models.TextField(blank=True, default='')
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='cancelled_orders'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    stock_restored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    VALID_TRANSITIONS = {
        'PENDING': ['PROCESSING', 'CANCELLED', 'FAILED'],
        'PROCESSING': ['SHIPPED', 'CANCELLED'],
        'SHIPPED': ['DELIVERED', 'RETURN_REQUESTED', 'DISPUTED'],
        'DELIVERED': ['RETURN_REQUESTED', 'REFUNDED', 'DISPUTED'],
        'RETURN_REQUESTED': ['RETURNED', 'PROCESSING', 'DISPUTED'],
        'RETURNED': ['REFUNDED', 'DISPUTED'],
        'DISPUTED': ['RESOLVED', 'REFUNDED', 'CANCELLED', 'PROCESSING'],
        'CANCELLED': ['REFUNDED'],
        'REFUNDED': [],
        'FAILED': [],
    }

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} - {self.product.name}"

    def can_transition_to(self, new_status, user=None):
        """Validate if order can transition to new_status based on current status and user role."""
        if self.status == new_status:
            return True, "Status is already up to date."
        
        allowed_targets = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed_targets:
            return False, f"Invalid transition: Cannot move order from {self.status} to {new_status}."

        if user:
            role = getattr(user, 'role', '')
            is_admin_user = role == 'ADMIN' or getattr(user, 'is_superuser', False)

            if not is_admin_user:
                if role == 'CUSTOMER':
                    if new_status == 'CANCELLED' and self.status not in ['PENDING', 'PROCESSING']:
                        return False, "Orders cannot be cancelled once they have been shipped."
                    if new_status == 'RETURN_REQUESTED' and self.status != 'DELIVERED':
                        return False, "Return requests can only be placed on delivered orders."
                    if new_status not in ['CANCELLED', 'RETURN_REQUESTED']:
                        return False, "Customers cannot set this order status directly."

                elif role == 'HANDICRAFTER':
                    if new_status not in ['PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'RETURNED']:
                        return False, "Sellers cannot set this order status directly."
                    if new_status == 'DELIVERED' and self.status != 'SHIPPED':
                        return False, "Order must be marked as Shipped before it can be marked Delivered."

        return True, "Valid transition."

    def restore_stock(self):
        """Idempotently restore stock for the ordered product."""
        if not self.stock_restored:
            self.product.stock += self.quantity
            self.product.save(update_fields=['stock'])
            self.stock_restored = True
            self.save(update_fields=['stock_restored'])
            return True
        return False

    def add_timeline(self, status, title, notes="", changed_by=None):
        return OrderTimeline.objects.create(
            order=self,
            status=status,
            title=title,
            notes=notes,
            changed_by=changed_by
        )


class OrderTimeline(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='timeline'
    )
    status = models.CharField(max_length=40)
    title = models.CharField(max_length=150)
    notes = models.TextField(blank=True, default='')
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='order_timeline_events'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Order #{self.order_id} - {self.title} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


class RefundRequest(models.Model):
    REASON_CHOICES = (
        ('DEFECTIVE', 'Defective or Damaged Product'),
        ('WRONG_ITEM', 'Wrong Item Received'),
        ('NOT_AS_DESCRIBED', 'Product Not as Described'),
        ('CANCELLED_ORDER', 'Order Cancelled Before Shipping'),
        ('LATE_DELIVERY', 'Delivery Delayed / Not Received'),
        ('OTHER', 'Other Reason'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending Admin Review'),
        ('APPROVED', 'Approved & Reconciled'),
        ('REJECTED', 'Rejected'),
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='refund_requests'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='refund_requests'
    )
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    explanation = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    admin_notes = models.TextField(blank=True, default='')
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='decided_refund_requests'
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"RefundRequest #{self.id} for Order #{self.order_id} - ₹{self.amount} ({self.status})"


class PaymentReconciliation(models.Model):
    STATUS_CHOICES = (
        ('SUCCESS', 'Success'),
        ('PENDING', 'Pending'),
        ('FAILED', 'Failed'),
        ('SIMULATED', 'Manual / Simulated Reconciliation'),
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='payment_reconciliations'
    )
    refund_request = models.ForeignKey(
        RefundRequest,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reconciliations'
    )
    payment_intent_id = models.CharField(max_length=255, blank=True, default='')
    refund_transaction_id = models.CharField(max_length=255, blank=True, default='')
    original_amount = models.DecimalField(max_digits=10, decimal_places=2)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2)
    gateway_status = models.CharField(max_length=50, default='SUCCEEDED')
    is_reconciled = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default='')
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Reconciliation for Order #{self.order_id} - ₹{self.refunded_amount} ({self.gateway_status})"


class Review(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='review',
        null=True,
        blank=True
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True, default='')
    seller_reply = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Review by {self.customer.name} on {self.product.name}"


class SellerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='seller_profile'
    )
    bio = models.TextField(blank=True, default='')
    craft_story = models.TextField(blank=True, default='')
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    cover_banner = models.ImageField(upload_to='banners/', blank=True, null=True)
    craft_specialty = models.CharField(max_length=200, blank=True, default='')
    workshop_headline = models.CharField(max_length=200, blank=True, default='')
    years_of_experience = models.PositiveIntegerField(default=1)
    techniques_used = models.CharField(max_length=300, blank=True, default='')
    materials_used = models.CharField(max_length=300, blank=True, default='')
    badge_label = models.CharField(max_length=100, blank=True, default='Master Artisan')
    location = models.CharField(max_length=200, blank=True, default='')
    social_links = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.name}"


class WorkshopPhoto(models.Model):
    seller_profile = models.ForeignKey(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name='workshop_photos'
    )
    image = models.ImageField(upload_to='workshops/')
    caption = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Workshop photo for {self.seller_profile.user.name}"


class Earning(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('CANCELLED', 'Cancelled'),
        ('REFUNDED', 'Refunded'),
    )

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='earnings'
    )
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='earning'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission = models.DecimalField(max_digits=10, decimal_places=2)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Earning ₹{self.net_amount} for Order #{self.order.id}"


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user.name}"

    @property
    def total_items(self):
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0

    @property
    def subtotal(self):
        total = sum(item.line_total for item in self.items.all())
        return round(total, 2)


class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='cart_items'
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'product')

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"

    @property
    def line_total(self):
        return float(self.product.price) * self.quantity


class Wishlist(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wishlist'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='wishlisted_by'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.name} ♥ {self.product.name}"


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_profile'
    )
    phone = models.CharField(max_length=15, blank=True, default='')
    address = models.TextField(blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    pincode = models.CharField(max_length=10, blank=True, default='')
    profile_picture = models.ImageField(upload_to='customer_profiles/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.name}"


class CommissionSetting(models.Model):
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=10.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='commission_updates'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Commission Setting'
        verbose_name_plural = 'Commission Settings'

    def __str__(self):
        return f"Platform Commission: {self.percentage}%"

    @classmethod
    def get_rate(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'percentage': 10.00})
        return obj.percentage


class Dispute(models.Model):
    TYPE_CHOICES = (
        ('CUSTOMER_COMPLAINT', 'Customer Complaint'),
        ('SELLER_COMPLAINT', 'Seller Complaint'),
        ('REFUND_REQUEST', 'Refund Request'),
    )
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('UNDER_REVIEW', 'Under Review'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='disputes'
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='disputes'
    )
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    resolution = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Dispute #{self.id} — {self.subject}"


class ProductEmbedding(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='embedding'
    )
    # Store the 1536-dimensional vector as a JSON list of floats
    vector = models.JSONField(default=list)
    text_content = models.TextField(help_text="The raw text used to generate this embedding")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Embedding for {self.product.name}"


class BrowsingHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='browsing_history'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='browsed_by'
    )
    view_count = models.PositiveIntegerField(default=1)
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_viewed_at']
        unique_together = ('user', 'product')

    def __str__(self):
        return f"{self.user.name} viewed {self.product.name} ({self.view_count}x)"


class UserCategoryInterest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='category_interests'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='interested_users'
    )
    score = models.FloatField(default=1.0, help_text="Interest affinity score (updated from browsing/explicit)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-score']
        unique_together = ('user', 'category')

    def __str__(self):
        return f"{self.user.name} interest in {self.category.name}: {self.score}"


class SellerPayout(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('PROCESSING', 'Processing Transfer'),
        ('PAID', 'Paid / Completed'),
        ('REJECTED', 'Rejected'),
    )
    PAYOUT_METHOD_CHOICES = (
        ('BANK_TRANSFER', 'Bank Transfer (NEFT/IMPS)'),
        ('UPI', 'UPI Direct'),
        ('STRIPE', 'Stripe Connect'),
    )

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payouts'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payout_method = models.CharField(max_length=30, choices=PAYOUT_METHOD_CHOICES, default='BANK_TRANSFER')
    account_details = models.TextField(help_text="Account number, IFSC, or UPI ID")
    reference_id = models.CharField(max_length=100, blank=True, default='', help_text="Transaction reference / UTR / Transfer ID")
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='decided_payouts'
    )

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"Payout #{self.id} for {self.seller.name} - ₹{self.amount} ({self.status})"


class SellerLedgerEntry(models.Model):
    ENTRY_TYPES = (
        ('SALE', 'Gross Order Sale'),
        ('COMMISSION', 'Platform Commission Fee'),
        ('REFUND', 'Customer Refund Deduction'),
        ('PAYOUT', 'Payout Disbursement'),
        ('ADJUSTMENT', 'Balance Adjustment'),
    )

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ledger_entries'
    )
    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_credit = models.BooleanField(help_text="True if adds to seller balance, False if deducts")
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, help_text="Running available balance after this entry")
    order = models.ForeignKey(
        Order,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='ledger_entries'
    )
    payout = models.ForeignKey(
        SellerPayout,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='ledger_entries'
    )
    description = models.CharField(max_length=255)
    reference_id = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        sign = '+' if self.is_credit else '-'
        return f"Ledger #{self.id} [{self.seller.name}] {sign}₹{self.amount} ({self.entry_type}) -> Balance: ₹{self.balance_after}"

    @classmethod
    def get_seller_balance(cls, seller):
        latest = cls.objects.filter(seller=seller).order_by('-created_at', '-id').first()
        if latest:
            return latest.balance_after
        return Decimal('0.00')

    @classmethod
    def record(cls, seller, entry_type, amount, is_credit, description, order=None, payout=None, reference_id=''):
        amount_dec = Decimal(str(amount))
        current_balance = cls.get_seller_balance(seller)
        new_balance = current_balance + amount_dec if is_credit else current_balance - amount_dec
        return cls.objects.create(
            seller=seller,
            entry_type=entry_type,
            amount=amount_dec,
            is_credit=is_credit,
            balance_after=new_balance,
            order=order,
            payout=payout,
            description=description,
            reference_id=reference_id
        )

