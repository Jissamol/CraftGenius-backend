from rest_framework import serializers
from django.db import models as db_models
from .models import (
    Category, Product, ProductImage, Order, Review,
    SellerProfile, Earning, CommissionSetting, Dispute
)
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


class AdminUserSerializer(serializers.ModelSerializer):
    total_orders = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    total_products = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'name', 'email', 'role', 'is_approved',
            'is_active', 'created_at', 'total_orders', 'total_spent',
            'total_products'
        ]

    def get_total_orders(self, obj):
        if obj.role == 'CUSTOMER':
            return obj.customer_orders.count()
        return 0

    def get_total_spent(self, obj):
        if obj.role == 'CUSTOMER':
            total = obj.customer_orders.filter(
                status='DELIVERED'
            ).aggregate(
                total=db_models.Sum('total_amount')
            )['total']
            return float(total or 0)
        return 0

    def get_total_products(self, obj):
        if obj.role == 'HANDICRAFTER':
            return obj.products.count()
        return 0


class AdminHandicrafterSerializer(serializers.ModelSerializer):
    craft_specialty = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'name', 'email', 'role', 'is_approved',
            'is_active', 'created_at', 'craft_specialty',
            'location', 'product_count'
        ]

    def get_craft_specialty(self, obj):
        try:
            return obj.seller_profile.craft_specialty
        except Exception:
            return ''

    def get_location(self, obj):
        try:
            return obj.seller_profile.location
        except Exception:
            return ''

    def get_product_count(self, obj):
        return obj.products.count()


class AdminProductSerializer(serializers.ModelSerializer):
    seller_name = serializers.CharField(source='seller.name', read_only=True)
    category_name = serializers.SerializerMethodField()
    primary_image_url = serializers.SerializerMethodField()
    order_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'seller', 'seller_name', 'category',
            'category_name', 'price', 'stock', 'is_active',
            'is_approved', 'primary_image_url', 'order_count',
            'created_at'
        ]

    def get_category_name(self, obj):
        return obj.category.name if obj.category else ''

    def get_primary_image_url(self, obj):
        img = obj.primary_image
        if img:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return ''

    def get_order_count(self, obj):
        return obj.orders.count()


class AdminOrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    seller_name = serializers.CharField(source='seller.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'customer', 'customer_name', 'customer_email',
            'seller', 'seller_name', 'product', 'product_name',
            'product_image', 'quantity', 'total_amount', 'status',
            'tracking_number', 'created_at', 'updated_at'
        ]

    def get_product_image(self, obj):
        img = obj.product.primary_image
        if img:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(img.image.url)
            return img.image.url
        return ''


class AdminReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    seller_name = serializers.CharField(source='product.seller.name', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'product', 'product_name', 'customer',
            'customer_name', 'seller_name', 'rating', 'comment',
            'seller_reply', 'created_at'
        ]


class AdminCategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'image', 'product_count', 'created_at']

    def get_product_count(self, obj):
        return obj.products.count()


class CommissionSettingSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source='updated_by.name', read_only=True)

    class Meta:
        model = CommissionSetting
        fields = ['id', 'percentage', 'updated_by', 'updated_by_name', 'updated_at']
        read_only_fields = ['updated_by', 'updated_by_name', 'updated_at']


class DisputeSerializer(serializers.ModelSerializer):
    raised_by_name = serializers.CharField(source='raised_by.name', read_only=True)
    order_product = serializers.CharField(source='order.product.name', read_only=True)
    order_customer = serializers.CharField(source='order.customer.name', read_only=True)
    order_seller = serializers.CharField(source='order.seller.name', read_only=True)

    class Meta:
        model = Dispute
        fields = [
            'id', 'order', 'order_product', 'order_customer',
            'order_seller', 'raised_by', 'raised_by_name', 'type',
            'subject', 'description', 'status', 'resolution',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['raised_by', 'raised_by_name', 'created_at', 'updated_at']
