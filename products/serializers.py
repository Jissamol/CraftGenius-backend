from rest_framework import serializers
from .models import (
    Category, Product, ProductImage, Order, Review,
    SellerProfile, Earning, Cart, CartItem, Wishlist, CustomerProfile
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

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'category', 'category_name',
            'price', 'stock', 'tags', 'is_active', 'images',
            'primary_image_url', 'seller_name', 'average_rating',
            'total_orders', 'created_at', 'updated_at'
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


class ProductCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['name', 'description', 'category', 'price', 'stock', 'tags', 'is_active']

    def create(self, validated_data):
        validated_data['seller'] = self.context['request'].user
        return super().create(validated_data)


class OrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'customer', 'customer_name', 'customer_email',
            'product', 'product_name', 'product_image',
            'seller', 'quantity', 'total_amount', 'status',
            'tracking_number', 'created_at', 'updated_at'
        ]
        read_only_fields = ['customer', 'product', 'seller', 'total_amount']

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
        choices=['PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED']
    )
    tracking_number = serializers.CharField(required=False, allow_blank=True)


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


class SellerProfileSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='user.name', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = SellerProfile
        fields = [
            'id', 'name', 'email', 'bio', 'profile_picture',
            'craft_specialty', 'location', 'social_links',
            'created_at', 'updated_at'
        ]


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

