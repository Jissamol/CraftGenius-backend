from django.contrib import admin
from .models import (
    Category, Product, ProductImage, Order, Review,
    SellerProfile, Earning, Cart, CartItem, Wishlist, CustomerProfile,
    CommissionSetting, Dispute
)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'seller', 'category', 'price', 'stock', 'is_active', 'is_approved', 'created_at']
    list_filter = ['is_active', 'is_approved', 'category', 'created_at']
    search_fields = ['name', 'seller__name']
    inlines = [ProductImageInline]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'product', 'seller', 'quantity', 'total_amount', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['customer__name', 'product__name', 'seller__name']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'customer', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['product__name', 'customer__name']


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'craft_specialty', 'location']
    search_fields = ['user__name', 'craft_specialty']


@admin.register(Earning)
class EarningAdmin(admin.ModelAdmin):
    list_display = ['seller', 'order', 'amount', 'commission', 'net_amount', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['seller__name']


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['user', 'total_items', 'subtotal', 'updated_at']
    inlines = [CartItemInline]


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'product', 'added_at']
    list_filter = ['added_at']
    search_fields = ['user__name', 'product__name']


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone', 'city', 'state']
    search_fields = ['user__name', 'phone']


@admin.register(CommissionSetting)
class CommissionSettingAdmin(admin.ModelAdmin):
    list_display = ['percentage', 'updated_by', 'updated_at']


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ['id', 'subject', 'type', 'status', 'raised_by', 'created_at']
    list_filter = ['type', 'status', 'created_at']
    search_fields = ['subject', 'raised_by__name']
