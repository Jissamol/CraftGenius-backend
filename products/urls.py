from django.urls import path
from . import views, admin_views, stripe_views

urlpatterns = [
    # ──────────── Stripe Endpoints ────────────
    path('stripe/create-session/', stripe_views.create_checkout_session, name='stripe-create-session'),
    path('stripe/webhook/', stripe_views.stripe_webhook, name='stripe-webhook'),
    path('stripe/payment-success/', stripe_views.payment_success_view, name='stripe-payment-success'),

    # ──────────── Seller Endpoints ────────────
    # Categories
    path('categories/', views.category_list, name='category-list'),

    # Products (seller)
    path('products/my/', views.my_products, name='my-products'),
    path('products/create/', views.create_product, name='create-product'),
    path('products/<int:pk>/update/', views.update_product, name='update-product'),
    path('products/<int:pk>/delete/', views.delete_product, name='delete-product'),

    # Orders (seller)
    path('orders/seller/', views.seller_orders, name='seller-orders'),
    path('orders/<int:pk>/status/', views.update_order_status, name='update-order-status'),

    # Reviews (seller)
    path('reviews/seller/', views.seller_reviews, name='seller-reviews'),
    path('reviews/<int:pk>/reply/', views.reply_to_review, name='reply-to-review'),

    # Seller Profile & Workshop Photos
    path('seller/profile/', views.seller_profile, name='seller-profile'),
    path('seller/workshop-photos/', views.add_workshop_photo, name='add-workshop-photo'),
    path('seller/workshop-photos/<int:pk>/', views.delete_workshop_photo, name='delete-workshop-photo'),

    # Public Artisan Storefronts
    path('artisan/<int:pk>/', views.artisan_storefront, name='artisan-storefront'),
    path('artisans/', views.artisan_list, name='artisan-list'),

    # Earnings
    path('seller/earnings/', views.seller_earnings, name='seller-earnings'),

    # Analytics
    path('seller/analytics/', views.seller_analytics, name='seller-analytics'),

    # Overview
    path('seller/overview/', views.seller_overview, name='seller-overview'),

    # ──────────── Customer Endpoints ────────────
    # Product Browse
    path('products/', views.product_list, name='product-list'),
    path('products/<int:pk>/', views.product_detail, name='product-detail'),
    path('products/<int:pk>/track-view/', views.track_product_view, name='track-product-view'),
    path('products/image-search/', views.product_image_search, name='product-image-search'),

    # Cart
    path('cart/', views.get_cart, name='get-cart'),
    path('cart/add/', views.add_to_cart, name='add-to-cart'),
    path('cart/update/<int:pk>/', views.update_cart_item, name='update-cart-item'),
    path('cart/remove/<int:pk>/', views.remove_cart_item, name='remove-cart-item'),

    # Orders (customer)
    path('orders/create/', views.create_order, name='create-order'),
    path('orders/customer/', views.customer_orders, name='customer-orders'),
    path('orders/<int:pk>/cancel/', views.cancel_order, name='cancel-order'),
    path('orders/<int:pk>/request-refund/', views.request_refund, name='request-refund'),
    path('orders/<int:pk>/timeline/', views.order_timeline, name='order-timeline'),

    # Wishlist
    path('wishlist/', views.get_wishlist, name='get-wishlist'),
    path('wishlist/add/', views.add_to_wishlist, name='add-to-wishlist'),
    path('wishlist/remove/<int:pk>/', views.remove_from_wishlist, name='remove-from-wishlist'),

    # Reviews (customer)
    path('reviews/', views.create_review, name='create-review'),
    path('reviews/<int:pk>/edit/', views.edit_review, name='edit-review'),
    path('reviews/<int:pk>/delete/', views.delete_review, name='delete-review'),
    path('reviews/customer/', views.customer_reviews, name='customer-reviews'),

    # Customer Profile
    path('customer/profile/', views.customer_profile, name='customer-profile'),

    # Recommendations
    path('recommendations/', views.recommendations, name='recommendations'),
    path('recommendations/interests/', views.user_category_interests, name='user-category-interests'),

    # AI Chat Assistant
    path('chat/', views.chat_assistant, name='chat-assistant'),

    # ──────────── Admin Endpoints ────────────
    path('admin/dashboard/', admin_views.admin_dashboard, name='admin-dashboard'),
    path('admin/analytics/', admin_views.admin_analytics, name='admin-analytics'),

    # Handicrafters
    path('admin/handicrafters/', admin_views.admin_handicrafters, name='admin-handicrafters'),
    path('admin/handicrafters/<int:pk>/approve/', admin_views.admin_approve_handicrafter, name='admin-approve-handicrafter'),
    path('admin/handicrafters/<int:pk>/reject/', admin_views.admin_reject_handicrafter, name='admin-reject-handicrafter'),

    # Products
    path('admin/products/', admin_views.admin_products, name='admin-products'),
    path('admin/products/<int:pk>/approve/', admin_views.admin_approve_product, name='admin-approve-product'),
    path('admin/products/<int:pk>/reject/', admin_views.admin_reject_product, name='admin-reject-product'),
    path('admin/products/<int:pk>/', admin_views.admin_delete_product, name='admin-delete-product'),

    # Orders
    path('admin/orders/', admin_views.admin_orders, name='admin-orders'),
    path('admin/orders/<int:pk>/status/', admin_views.admin_update_order_status, name='admin-update-order-status'),
    path('admin/orders/<int:pk>/refund/', admin_views.admin_refund_order, name='admin-refund-order'),
    path('admin/refund-requests/', admin_views.admin_refund_requests, name='admin-refund-requests'),
    path('admin/refund-requests/<int:pk>/decide/', admin_views.admin_decide_refund_request, name='admin-decide-refund-request'),

    # Customers
    path('admin/customers/', admin_views.admin_customers, name='admin-customers'),
    path('admin/customers/<int:pk>/toggle/', admin_views.admin_toggle_customer, name='admin-toggle-customer'),

    # Categories
    path('admin/categories/', admin_views.admin_categories, name='admin-categories'),
    path('admin/categories/<int:pk>/', admin_views.admin_category_detail, name='admin-category-detail'),

    # Reviews
    path('admin/reviews/', admin_views.admin_reviews, name='admin-reviews'),
    path('admin/reviews/<int:pk>/', admin_views.admin_delete_review, name='admin-delete-review'),

    # Disputes
    path('admin/disputes/', admin_views.admin_disputes, name='admin-disputes'),
    path('admin/disputes/<int:pk>/', admin_views.admin_update_dispute, name='admin-update-dispute'),

    # Commission
    path('admin/commission/', admin_views.admin_commission, name='admin-commission'),
]
