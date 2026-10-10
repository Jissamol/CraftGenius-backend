from rest_framework import serializers
from .models import (
    Category, Product, ProductImage, Order, Review,
    SellerProfile, Earning, Cart, CartItem, Wishlist, CustomerProfile,
    OrderTimeline, RefundRequest, PaymentReconciliation, WorkshopPhoto
)



class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'image']


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'is_primary']


class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default='')
    seller_name = serializers.CharField(source='seller.name', read_only=True)
    average_rating = serializers.FloatField(read_only=True)
    total_orders = serializers.IntegerField(read_only=True)
    primary_image_url = serializers.SerializerMethodField()
    recommendation_reason = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'category', 'category_name',
            'price', 'stock', 'tags', 'is_active', 'images',
            'primary_image_url', 'seller_name', 'average_rating',
            'total_orders', 'recommendation_reason', 'created_at', 'updated_at'
        ]
        read_only_fields = ['seller']

    def get_primary_image_url(self, obj):
        img = obj.primary_image
        if img and img.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None

    def get_recommendation_reason(self, obj):
        return getattr(obj, 'recommendation_reason', None)


class ProductCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['name', 'description', 'category', 'price', 'stock', 'tags', 'is_active']

    def create(self, validated_data):
        validated_data['seller'] = self.context['request'].user
        return super().create(validated_data)


class OrderTimelineSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.name', read_only=True, default='')

    class Meta:
        model = OrderTimeline
        fields = ['id', 'status', 'title', 'notes', 'changed_by', 'changed_by_name', 'created_at']


class RefundRequestSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = RefundRequest
        fields = [
            'id', 'order', 'customer', 'customer_name', 'reason',
            'reason_display', 'explanation', 'amount', 'status',
            'status_display', 'admin_notes', 'decided_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['customer', 'status', 'admin_notes', 'decided_at']


class PaymentReconciliationSerializer(serializers.ModelSerializer):
    reconciled_by_name = serializers.CharField(source='reconciled_by.name', read_only=True, default='')

    class Meta:
        model = PaymentReconciliation
        fields = [
            'id', 'order', 'refund_request', 'payment_intent_id',
            'refund_transaction_id', 'original_amount', 'refunded_amount',
            'gateway_status', 'is_reconciled', 'notes', 'reconciled_by',
            'reconciled_by_name', 'created_at'
        ]


class OrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    seller_name = serializers.CharField(source='seller.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    timeline = OrderTimelineSerializer(many=True, read_only=True)
    refund_requests = RefundRequestSerializer(many=True, read_only=True)
    payment_reconciliations = PaymentReconciliationSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'customer', 'customer_name', 'customer_email',
            'product', 'product_name', 'product_image',
            'seller', 'seller_name', 'quantity', 'total_amount', 'status',
            'is_paid', 'stripe_payment_intent', 'tracking_number',
            'cancellation_reason', 'cancelled_at', 'stock_restored',
            'timeline', 'refund_requests', 'payment_reconciliations',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['customer', 'product', 'seller', 'total_amount', 'is_paid']

    def get_product_image(self, obj):
        img = obj.product.primary_image
        if img and img.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None


class OrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=['PENDING', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'RETURNED', 'REFUNDED']
    )
    tracking_number = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            'id', 'product', 'product_name', 'product_image', 'customer',
            'customer_name', 'rating', 'comment',
            'seller_reply', 'created_at', 'updated_at'
        ]
        read_only_fields = ['product', 'customer', 'rating', 'comment']

    def get_product_image(self, obj):
        img = obj.product.primary_image
        if img and img.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None


class ReviewReplySerializer(serializers.Serializer):
    seller_reply = serializers.CharField()


class WorkshopPhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = WorkshopPhoto
        fields = ['id', 'image', 'image_url', 'caption', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None


class SellerProfileSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='user.name', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    address = serializers.CharField(source='user.address', read_only=True)
    role = serializers.CharField(source='user.role', read_only=True)
    is_approved = serializers.BooleanField(source='user.is_approved', read_only=True)
    workshop_photos = WorkshopPhotoSerializer(many=True, read_only=True)

    def get_profile_picture(self, obj):
        request = self.context.get('request')
        if obj.profile_picture:
            return request.build_absolute_uri(obj.profile_picture.url) if request else obj.profile_picture.url
        elif obj.user.profile_picture:
            return request.build_absolute_uri(obj.user.profile_picture.url) if request else obj.user.profile_picture.url
        return None

    def get_cover_banner_url(self, obj):
        request = self.context.get('request')
        if obj.cover_banner:
            return request.build_absolute_uri(obj.cover_banner.url) if request else obj.cover_banner.url
        return None

    profile_picture_url = serializers.SerializerMethodField(method_name='get_profile_picture')
    cover_banner_url = serializers.SerializerMethodField(method_name='get_cover_banner_url')

    class Meta:
        model = SellerProfile
        fields = [
            'id', 'name', 'email', 'phone_number', 'address', 'role', 'is_approved',
            'bio', 'craft_story', 'profile_picture', 'profile_picture_url',
            'cover_banner', 'cover_banner_url', 'craft_specialty',
            'workshop_headline', 'years_of_experience', 'techniques_used',
            'materials_used', 'badge_label', 'location', 'social_links',
            'workshop_photos', 'created_at', 'updated_at'
        ]


class ArtisanStorefrontSerializer(serializers.ModelSerializer):
    seller_id = serializers.IntegerField(source='user.id', read_only=True)
    name = serializers.CharField(source='user.name', read_only=True)
    is_verified = serializers.BooleanField(source='user.is_approved', read_only=True)
    member_since = serializers.DateTimeField(source='user.created_at', read_only=True)
    workshop_photos = WorkshopPhotoSerializer(many=True, read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    cover_banner_url = serializers.SerializerMethodField()
    total_products = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    total_reviews = serializers.SerializerMethodField()
    fulfilled_orders = serializers.SerializerMethodField()

    class Meta:
        model = SellerProfile
        fields = [
            'id', 'seller_id', 'name', 'is_verified', 'member_since',
            'bio', 'craft_story', 'profile_picture_url', 'cover_banner_url',
            'craft_specialty', 'workshop_headline', 'years_of_experience',
            'techniques_used', 'materials_used', 'badge_label', 'location',
            'social_links', 'workshop_photos', 'total_products',
            'average_rating', 'total_reviews', 'fulfilled_orders'
        ]

    def get_profile_picture_url(self, obj):
        request = self.context.get('request')
        if obj.profile_picture:
            return request.build_absolute_uri(obj.profile_picture.url) if request else obj.profile_picture.url
        elif obj.user.profile_picture:
            return request.build_absolute_uri(obj.user.profile_picture.url) if request else obj.user.profile_picture.url
        return None

    def get_cover_banner_url(self, obj):
        request = self.context.get('request')
        if obj.cover_banner:
            return request.build_absolute_uri(obj.cover_banner.url) if request else obj.cover_banner.url
        return None

    def get_total_products(self, obj):
        return obj.user.products.filter(is_active=True, is_approved=True).count()

    def get_fulfilled_orders(self, obj):
        return obj.user.seller_orders.filter(status='DELIVERED').count()

    def get_average_rating(self, obj):
        from django.db.models import Avg
        avg = Review.objects.filter(product__seller=obj.user).aggregate(avg=Avg('rating'))['avg']
        return round(float(avg), 1) if avg else 5.0

    def get_total_reviews(self, obj):
        return Review.objects.filter(product__seller=obj.user).count()


class EarningSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    product_name = serializers.CharField(source='order.product.name', read_only=True)

    class Meta:
        model = Earning
        fields = [
            'id', 'order_id', 'product_name', 'amount',
            'commission', 'net_amount', 'status',
            'paid_at', 'created_at'
        ]


# ──────────────────── Customer Serializers ──────────────────────

class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2, read_only=True)
    product_image = serializers.SerializerMethodField()
    line_total = serializers.FloatField(read_only=True)
    seller_name = serializers.CharField(source='product.seller.name', read_only=True)
    stock = serializers.IntegerField(source='product.stock', read_only=True)

    class Meta:
        model = CartItem
        fields = [
            'id', 'product', 'product_name', 'product_price',
            'product_image', 'seller_name', 'stock',
            'quantity', 'line_total', 'added_at'
        ]

    def get_product_image(self, obj):
        img = obj.product.primary_image
        if img and img.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    subtotal = serializers.FloatField(read_only=True)

    class Meta:
        model = Cart
        fields = ['id', 'items', 'total_items', 'subtotal', 'updated_at']


class WishlistSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2, read_only=True)
    product_image = serializers.SerializerMethodField()
    seller_name = serializers.CharField(source='product.seller.name', read_only=True)
    average_rating = serializers.FloatField(source='product.average_rating', read_only=True)
    stock = serializers.IntegerField(source='product.stock', read_only=True)

    class Meta:
        model = Wishlist
        fields = [
            'id', 'product', 'product_name', 'product_price',
            'product_image', 'seller_name', 'average_rating',
            'stock', 'added_at'
        ]

    def get_product_image(self, obj):
        img = obj.product.primary_image
        if img and img.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None


class CustomerProfileSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='user.name', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = CustomerProfile
        fields = [
            'id', 'name', 'email', 'phone', 'address',
            'city', 'state', 'pincode', 'profile_picture',
            'created_at', 'updated_at'
        ]


class CustomerReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['product', 'order', 'rating', 'comment']


class ProductDetailSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default='')
    seller_name = serializers.CharField(source='seller.name', read_only=True)
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    average_rating = serializers.FloatField(read_only=True)
    total_orders = serializers.IntegerField(read_only=True)
    primary_image_url = serializers.SerializerMethodField()
    reviews = ReviewSerializer(many=True, read_only=True)
    is_wishlisted = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'category', 'category_name',
            'price', 'stock', 'tags', 'is_active', 'images',
            'primary_image_url', 'seller_name', 'seller_id',
            'average_rating', 'total_orders', 'reviews',
            'is_wishlisted', 'created_at', 'updated_at'
        ]

    def get_primary_image_url(self, obj):
        img = obj.primary_image
        if img and img.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return None

    def get_is_wishlisted(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return Wishlist.objects.filter(user=request.user, product=obj).exists()
        return False

