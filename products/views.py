from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from PIL import Image
import os
import numpy as np
import google.generativeai as genai
from fastembed import TextEmbedding
from django.conf import settings
from django.db.models import Sum, Avg, Count, Q
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from datetime import timedelta


from .models import (
    Category, Product, ProductImage, Order, Review,
    SellerProfile, Earning, Cart, CartItem, Wishlist, CustomerProfile,
    CommissionSetting, ProductEmbedding
)
from .serializers import (
    CategorySerializer, ProductSerializer, ProductCreateSerializer,
    OrderSerializer, OrderStatusSerializer, ReviewSerializer,
    ReviewReplySerializer, SellerProfileSerializer, EarningSerializer,
    CartSerializer, CartItemSerializer, WishlistSerializer,
    CustomerProfileSerializer, CustomerReviewCreateSerializer,
    ProductDetailSerializer
)


# ──────────────────────────── Categories ────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def category_list(request):
    categories = Category.objects.all()
    serializer = CategorySerializer(categories, many=True, context={'request': request})
    return Response(serializer.data)


# ──────────────────────────── Products ──────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_products(request):
    products = Product.objects.filter(seller=request.user)

    # Search
    search = request.query_params.get('search', '')
    if search:
        products = products.filter(name__icontains=search)

    # Filter by category
    category_id = request.query_params.get('category')
    if category_id:
        products = products.filter(category_id=category_id)

    # Filter by active status
    is_active = request.query_params.get('is_active')
    if is_active is not None:
        products = products.filter(is_active=is_active.lower() == 'true')

    serializer = ProductSerializer(products, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def create_product(request):
    serializer = ProductCreateSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        product = serializer.save()

        # Handle multiple image uploads
        images = request.FILES.getlist('images')
        for i, image in enumerate(images):
            ProductImage.objects.create(
                product=product,
                image=image,
                is_primary=(i == 0)
            )

        result = ProductSerializer(product, context={'request': request})
        return Response(result.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def update_product(request, pk):
    try:
        product = Product.objects.get(pk=pk, seller=request.user)
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ProductCreateSerializer(product, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        product = serializer.save()

        # Handle new image uploads
        images = request.FILES.getlist('images')
        if images:
            # Remove old images if new ones are provided
            product.images.all().delete()
            for i, image in enumerate(images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    is_primary=(i == 0)
                )

        result = ProductSerializer(product, context={'request': request})
        return Response(result.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_product(request, pk):
    try:
        product = Product.objects.get(pk=pk, seller=request.user)
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

    product.delete()
    return Response({'detail': 'Product deleted successfully'}, status=status.HTTP_204_NO_CONTENT)


# ──────────────────────────── Orders ────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seller_orders(request):
    orders = Order.objects.filter(seller=request.user)

    # Filter by status
    order_status = request.query_params.get('status')
    if order_status:
        orders = orders.filter(status=order_status.upper())

    serializer = OrderSerializer(orders, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_order_status(request, pk):
    try:
        order = Order.objects.get(pk=pk, seller=request.user)
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = OrderStatusSerializer(data=request.data)
    if serializer.is_valid():
        order.status = serializer.validated_data['status']
        tracking = serializer.validated_data.get('tracking_number', '')
        if tracking:
            order.tracking_number = tracking
        order.save()

        # Auto-create Earning record when order is delivered
        if order.status == 'DELIVERED' and not hasattr(order, 'earning'):
            commission_rate = CommissionSetting.get_rate()
            amount = order.total_amount
            commission = round(amount * commission_rate / 100, 2)
            net_amount = amount - commission
            Earning.objects.create(
                seller=order.seller,
                order=order,
                amount=amount,
                commission=commission,
                net_amount=net_amount,
            )

        result = OrderSerializer(order, context={'request': request})
        return Response(result.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ──────────────────────────── Reviews ───────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seller_reviews(request):
    reviews = Review.objects.filter(product__seller=request.user)
    serializer = ReviewSerializer(reviews, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def reply_to_review(request, pk):
    try:
        review = Review.objects.get(pk=pk, product__seller=request.user)
    except Review.DoesNotExist:
        return Response({'detail': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ReviewReplySerializer(data=request.data)
    if serializer.is_valid():
        review.seller_reply = serializer.validated_data['seller_reply']
        review.save()
        result = ReviewSerializer(review, context={'request': request})
        return Response(result.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ──────────────────────────── Seller Profile ────────────────────────

@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def seller_profile(request):
    profile, created = SellerProfile.objects.get_or_create(user=request.user)

    if request.method == 'GET':
        serializer = SellerProfileSerializer(profile, context={'request': request})
        return Response(serializer.data)

    # PUT
    serializer = SellerProfileSerializer(profile, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ──────────────────────────── Earnings ──────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seller_earnings(request):
    earnings = Earning.objects.filter(seller=request.user)

    total = earnings.aggregate(
        total_amount=Sum('amount'),
        total_commission=Sum('commission'),
        total_net=Sum('net_amount')
    )

    withdrawable = earnings.filter(status='PENDING').aggregate(
        amount=Sum('net_amount')
    )['amount'] or 0

    serializer = EarningSerializer(earnings, many=True, context={'request': request})

    return Response({
        'total_earnings': total['total_amount'] or 0,
        'total_commission': total['total_commission'] or 0,
        'total_net': total['total_net'] or 0,
        'withdrawable': withdrawable,
        'history': serializer.data
    })


# ──────────────────────────── Analytics ─────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seller_analytics(request):
    period = request.query_params.get('period', '30')
    try:
        days = int(period)
    except ValueError:
        days = 30

    start_date = timezone.now() - timedelta(days=days)
    orders = Order.objects.filter(seller=request.user, created_at__gte=start_date)

    # Monthly revenue
    if days > 90:
        revenue_data = orders.annotate(
            period=TruncMonth('created_at')
        ).values('period').annotate(
            revenue=Sum('total_amount'),
            count=Count('id')
        ).order_by('period')
    else:
        revenue_data = orders.annotate(
            period=TruncDay('created_at')
        ).values('period').annotate(
            revenue=Sum('total_amount'),
            count=Count('id')
        ).order_by('period')

    # Best selling categories
    category_data = orders.values(
        'product__category__name'
    ).annotate(
        count=Count('id'),
        revenue=Sum('total_amount')
    ).order_by('-count')[:5]

    # Total metrics
    total_orders = orders.count()
    total_revenue = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    delivered = orders.filter(status='DELIVERED').count()
    conversion_rate = round((delivered / total_orders * 100), 1) if total_orders > 0 else 0

    return Response({
        'revenue_trend': [
            {
                'date': item['period'].strftime('%Y-%m-%d') if item['period'] else '',
                'revenue': float(item['revenue'] or 0),
                'orders': item['count']
            }
            for item in revenue_data
        ],
        'best_categories': [
            {
                'name': item['product__category__name'] or 'Uncategorized',
                'orders': item['count'],
                'revenue': float(item['revenue'] or 0)
            }
            for item in category_data
        ],
        'total_orders': total_orders,
        'total_revenue': float(total_revenue),
        'conversion_rate': conversion_rate
    })


# ──────────────────────────── Overview ──────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def seller_overview(request):
    user = request.user

    products = Product.objects.filter(seller=user)
    orders = Order.objects.filter(seller=user)
    reviews = Review.objects.filter(product__seller=user)

    total_products = products.count()
    total_orders = orders.count()
    pending_orders = orders.filter(status='PENDING').count()
    total_earnings = orders.filter(
        status='DELIVERED'
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0

    # Recent orders
    recent_orders = OrderSerializer(
        orders[:5], many=True, context={'request': request}
    ).data

    # Top selling product
    top_product = products.annotate(
        order_count=Count('orders')
    ).order_by('-order_count').first()

    top_product_data = None
    if top_product:
        top_product_data = ProductSerializer(top_product, context={'request': request}).data

    # Monthly sales (last 6 months)
    six_months_ago = timezone.now() - timedelta(days=180)
    monthly_sales = orders.filter(
        created_at__gte=six_months_ago
    ).annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(
        revenue=Sum('total_amount'),
        count=Count('id')
    ).order_by('month')

    return Response({
        'total_products': total_products,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'total_earnings': float(total_earnings),
        'average_rating': round(avg_rating, 1),
        'recent_orders': recent_orders,
        'top_product': top_product_data,
        'monthly_sales': [
            {
                'month': item['month'].strftime('%b %Y'),
                'revenue': float(item['revenue'] or 0),
                'orders': item['count']
            }
            for item in monthly_sales
        ]
    })


# ══════════════════════════════════════════════════════════════════
#                    CUSTOMER API VIEWS
# ══════════════════════════════════════════════════════════════════


# ──────────────────────────── Product Browse ─────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_list(request):
    """Public product listing with filters, search, sort, and pagination."""
    products = Product.objects.filter(is_active=True)

    # Search
    search = request.query_params.get('search', '')
    if search:
        products = products.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(tags__icontains=search) |
            Q(category__name__icontains=search)
        )

    # Filter by category
    category_id = request.query_params.get('category')
    if category_id:
        products = products.filter(category_id=category_id)

    # Filter by price range
    min_price = request.query_params.get('min_price')
    max_price = request.query_params.get('max_price')
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)

    # Filter by rating
    min_rating = request.query_params.get('min_rating')
    if min_rating:
        products = [p for p in products if p.average_rating >= float(min_rating)]
        product_ids = [p.id for p in products]
        products = Product.objects.filter(id__in=product_ids, is_active=True)

    # Filter by seller
    seller_id = request.query_params.get('seller')
    if seller_id:
        products = products.filter(seller_id=seller_id)

    # Filter by availability
    in_stock = request.query_params.get('in_stock')
    if in_stock == 'true':
        products = products.filter(stock__gt=0)

    # Sorting
    sort = request.query_params.get('sort', 'newest')
    if sort == 'price_low':
        products = products.order_by('price')
    elif sort == 'price_high':
        products = products.order_by('-price')
    elif sort == 'rating':
        products = products.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')
    else:  # newest
        products = products.order_by('-created_at')

    # Pagination
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 12))
    total = products.count()
    start = (page - 1) * page_size
    end = start + page_size
    paginated = products[start:end]

    serializer = ProductSerializer(paginated, many=True, context={'request': request})
    return Response({
        'products': serializer.data,
        'total': total,
        'page': page,
        'pages': (total + page_size - 1) // page_size
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def product_detail(request, pk):
    """Full product detail with images, reviews, seller info."""
    try:
        product = Product.objects.get(pk=pk, is_active=True)
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ProductDetailSerializer(product, context={'request': request})
    return Response(serializer.data)


# ──────────────────────────── Cart ──────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_cart(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    serializer = CartSerializer(cart, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_to_cart(request):
    product_id = request.data.get('product_id')
    quantity = int(request.data.get('quantity', 1))

    try:
        product = Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

    if quantity > product.stock:
        return Response({'detail': f'Only {product.stock} in stock'}, status=status.HTTP_400_BAD_REQUEST)

    cart, _ = Cart.objects.get_or_create(user=request.user)
    item, created = CartItem.objects.get_or_create(cart=cart, product=product)

    if not created:
        item.quantity += quantity
    else:
        item.quantity = quantity
    item.save()

    serializer = CartSerializer(cart, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_cart_item(request, pk):
    try:
        item = CartItem.objects.get(pk=pk, cart__user=request.user)
    except CartItem.DoesNotExist:
        return Response({'detail': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

    quantity = int(request.data.get('quantity', 1))
    if quantity <= 0:
        item.delete()
    else:
        if quantity > item.product.stock:
            return Response({'detail': f'Only {item.product.stock} in stock'}, status=status.HTTP_400_BAD_REQUEST)
        item.quantity = quantity
        item.save()

    cart = item.cart
    serializer = CartSerializer(cart, context={'request': request})
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_cart_item(request, pk):
    try:
        item = CartItem.objects.get(pk=pk, cart__user=request.user)
    except CartItem.DoesNotExist:
        return Response({'detail': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

    cart = item.cart
    item.delete()
    serializer = CartSerializer(cart, context={'request': request})
    return Response(serializer.data)


# ──────────────────────────── Orders (Customer) ─────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    """Create orders from cart items."""
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.all()

    if not items.exists():
        return Response({'detail': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

    orders_created = []
    for item in items:
        if item.quantity > item.product.stock:
            return Response(
                {'detail': f'{item.product.name} has only {item.product.stock} in stock'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order = Order.objects.create(
            customer=request.user,
            product=item.product,
            seller=item.product.seller,
            quantity=item.quantity,
            total_amount=item.line_total
        )
        # Reduce stock
        item.product.stock -= item.quantity
        item.product.save()

        orders_created.append(order)

    # Clear cart
    items.delete()

    serializer = OrderSerializer(orders_created, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_orders(request):
    orders = Order.objects.filter(customer=request.user)

    order_status = request.query_params.get('status')
    if order_status:
        orders = orders.filter(status=order_status.upper())

    serializer = OrderSerializer(orders, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def cancel_order(request, pk):
    try:
        order = Order.objects.get(pk=pk, customer=request.user)
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    if order.status in ['SHIPPED', 'DELIVERED']:
        return Response({'detail': 'Cannot cancel shipped/delivered orders'}, status=status.HTTP_400_BAD_REQUEST)

    order.status = 'CANCELLED'
    order.save()

    # Restore stock
    order.product.stock += order.quantity
    order.product.save()

    serializer = OrderSerializer(order, context={'request': request})
    return Response(serializer.data)


# ──────────────────────────── Wishlist ───────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wishlist(request):
    items = Wishlist.objects.filter(user=request.user)
    serializer = WishlistSerializer(items, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_to_wishlist(request):
    product_id = request.data.get('product_id')
    try:
        product = Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

    _, created = Wishlist.objects.get_or_create(user=request.user, product=product)
    if not created:
        return Response({'detail': 'Already in wishlist'}, status=status.HTTP_200_OK)

    return Response({'detail': 'Added to wishlist'}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_from_wishlist(request, pk):
    try:
        item = Wishlist.objects.get(pk=pk, user=request.user)
    except Wishlist.DoesNotExist:
        return Response({'detail': 'Item not found'}, status=status.HTTP_404_NOT_FOUND)

    item.delete()
    return Response({'detail': 'Removed from wishlist'}, status=status.HTTP_204_NO_CONTENT)


# ──────────────────────────── Reviews (Customer) ────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_review(request):
    serializer = CustomerReviewCreateSerializer(data=request.data)
    if serializer.is_valid():
        # Check if customer has ordered this product
        product = serializer.validated_data['product']
        has_ordered = Order.objects.filter(
            customer=request.user, product=product, status='DELIVERED'
        ).exists()

        if not has_ordered:
            return Response(
                {'detail': 'You can only review products you have purchased'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check for existing review
        existing = Review.objects.filter(customer=request.user, product=product).first()
        if existing:
            return Response(
                {'detail': 'You have already reviewed this product. Use edit instead.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer.save(customer=request.user)
        return Response(ReviewSerializer(serializer.instance, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def edit_review(request, pk):
    try:
        review = Review.objects.get(pk=pk, customer=request.user)
    except Review.DoesNotExist:
        return Response({'detail': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)

    review.rating = request.data.get('rating', review.rating)
    review.comment = request.data.get('comment', review.comment)
    review.save()

    serializer = ReviewSerializer(review, context={'request': request})
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_review(request, pk):
    try:
        review = Review.objects.get(pk=pk, customer=request.user)
    except Review.DoesNotExist:
        return Response({'detail': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)

    review.delete()
    return Response({'detail': 'Review deleted'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_reviews(request):
    reviews = Review.objects.filter(customer=request.user)
    serializer = ReviewSerializer(reviews, many=True, context={'request': request})
    return Response(serializer.data)


# ──────────────────────────── Customer Profile ──────────────────

@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def customer_profile(request):
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)

    if request.method == 'GET':
        serializer = CustomerProfileSerializer(profile, context={'request': request})

        # Add order stats
        orders = Order.objects.filter(customer=request.user)
        total_orders = orders.count()
        total_spent = orders.filter(status='DELIVERED').aggregate(
            Sum('total_amount'))['total_amount__sum'] or 0

        data = serializer.data
        data['total_orders'] = total_orders
        data['total_spent'] = float(total_spent)
        return Response(data)

    serializer = CustomerProfileSerializer(profile, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ──────────────────────────── Recommendations ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recommendations(request):
    """AI-based recommendations: personalized, trending, similar."""
    user = request.user

    # Products the user has ordered or has in wishlist
    ordered_product_ids = Order.objects.filter(customer=user).values_list('product_id', flat=True)
    wishlist_product_ids = Wishlist.objects.filter(user=user).values_list('product_id', flat=True)
    
    combined_product_ids = list(ordered_product_ids) + list(wishlist_product_ids)

    # Get categories the user is interested in
    interest_categories = Product.objects.filter(
        id__in=combined_product_ids
    ).values_list('category_id', flat=True).distinct()

    # Recommended: categories of interest, excluding what they already have/bought
    recommended = Product.objects.filter(
        is_active=True, 
        category_id__in=interest_categories
    ).exclude(id__in=combined_product_ids).order_by('-created_at')[:12]

    # Fallback for new users: Show top rated products
    if recommended.count() < 4:
        top_rated = Product.objects.filter(is_active=True).annotate(
            avg_rating=Avg('reviews__rating')
        ).exclude(id__in=combined_product_ids).order_by('-avg_rating', '-created_at')[:12]
        
        # Combine and remove duplicates
        recommended_list = list(recommended)
        existing_ids = {p.id for p in recommended_list}
        for p in top_rated:
            if p.id not in existing_ids:
                recommended_list.append(p)
                if len(recommended_list) >= 12:
                    break
        recommended = recommended_list[:12]

    # Trending: most ordered in last 30 days
    thirty_days_ago = timezone.now() - timedelta(days=30)
    trending_ids = Order.objects.filter(
        created_at__gte=thirty_days_ago
    ).values('product_id').annotate(
        count=Count('id')
    ).order_by('-count').values_list('product_id', flat=True)[:12]
    
    trending = Product.objects.filter(id__in=trending_ids, is_active=True)

    # Fallback for trending: If no recent orders, show products with most total orders
    if trending.count() < 4:
        all_time_trending_ids = Order.objects.values('product_id').annotate(
            count=Count('id')
        ).order_by('-count').values_list('product_id', flat=True)[:12]
        
        trending = Product.objects.filter(id__in=all_time_trending_ids, is_active=True)
        
        # If still empty, show some random active products
        if trending.count() < 4:
            trending = Product.objects.filter(is_active=True).order_by('?')[:12]

    # New arrivals
    new_arrivals = Product.objects.filter(is_active=True).order_by('-created_at')[:12]

    ctx = {'request': request}
    return Response({
        'recommended': ProductSerializer(recommended, many=True, context=ctx).data,
        'trending': ProductSerializer(trending, many=True, context=ctx).data,
        'new_arrivals': ProductSerializer(new_arrivals, many=True, context=ctx).data,
    })


def extract_histogram(image_file):
    """Helper to extract a normalized color histogram from an image file."""
    try:
        with Image.open(image_file) as img:
            img = img.resize((100, 100)).convert('RGB')
            # Get histogram (768 values: 256 for each R, G, B)
            hist = img.histogram()
            # Normalize
            total = sum(hist)
            if total == 0:
                return [0] * len(hist)
            return [x / total for x in hist]
    except Exception as e:
        print(f"Error extracting histogram: {e}")
        return None


def calculate_similarity(h1, h2):
    """Histogram intersection similarity."""
    if not h1 or not h2:
        return 0
    return sum(min(a, b) for a, b in zip(h1, h2))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def product_image_search(request):
    """Search for products using an uploaded image."""
    image_file = request.FILES.get('image')
    if not image_file:
        return Response({'detail': 'No image provided'}, status=status.HTTP_400_BAD_REQUEST)

    # Extract histogram for the query image
    query_hist = extract_histogram(image_file)
    if not query_hist:
        return Response({'detail': 'Invalid image file'}, status=status.HTTP_400_BAD_REQUEST)

    # Get all active products
    products = Product.objects.filter(is_active=True)
    results = []

    for product in products:
        primary_img = product.primary_image
        if primary_img and primary_img.image:
            # For a production app, we would pre-calculate and cache these histograms
            # But for this implementation, we'll calculate on the fly for simplicity
            try:
                img_path = primary_img.image.path
                if os.path.exists(img_path):
                    prod_hist = extract_histogram(img_path)
                    similarity = calculate_similarity(query_hist, prod_hist)
                    if similarity > 0.1:  # Threshold to filter out completely different images
                        results.append({
                            'product': product,
                            'similarity': similarity
                        })
            except Exception as e:
                print(f"Error processing product {product.id}: {e}")
                continue

    # Sort by similarity descending
    results.sort(key=lambda x: x['similarity'], reverse=True)

    # Take top 12
    top_results = [r['product'] for r in results[:12]]
    serializer = ProductSerializer(top_results, many=True, context={'request': request})

    return Response({
        'products': serializer.data,
        'total': len(results)
    })

# ──────────────────────────── AI Chat Assistant ─────────────────────

def cosine_similarity(v1, v2):
    """Calculate cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0
    return dot_product / (norm_v1 * norm_v2)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_assistant(request):
    """RAG-powered chat assistant using local fastembed + free Google Gemini."""
    message = request.data.get('message', '').strip()
    if not message:
        return Response({'detail': 'Message is required'}, status=status.HTTP_400_BAD_REQUEST)

    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return Response({'detail': 'GEMINI_API_KEY not configured in .env'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        # 1. Embed the user's query locally (100% free, no API)
        embedding_model = TextEmbedding()
        # TextEmbedding returns a generator, so we list() it and take the first vector
        query_vector = list(embedding_model.embed([message]))[0]

        # 2. Retrieve top matching products using Cosine Similarity
        embeddings = ProductEmbedding.objects.filter(product__is_active=True).select_related('product')
        
        results = []
        for emb in embeddings:
            if emb.vector:
                prod_vector = np.array(emb.vector)
                similarity = cosine_similarity(query_vector, prod_vector)
                results.append((similarity, emb))

        # Sort by similarity descending, take top 4
        results.sort(key=lambda x: x[0], reverse=True)
        top_matches = [emb for sim, emb in results[:4]]
        top_products = [emb.product for emb in top_matches]

        # 3. Construct the context for the LLM
        context_parts = []
        for emb in top_matches:
            context_parts.append(f"Product ID {emb.product.id}:\n{emb.text_content}")
        context_str = "\n\n---\n\n".join(context_parts)

        system_prompt = (
            "You are the CraftGenius AI Artisan Matchmaker, a helpful shopping assistant for a marketplace of handcrafted goods. "
            "Your goal is to help the user find the perfect handcrafted item. "
            "Use the provided context containing relevant products to answer the user's query and make recommendations. "
            "Be enthusiastic, polite, and highlight the artisans and the craftsmanship behind the products. "
            "Do NOT make up any products that are not in the context. If no products in the context fit the query, politely say you couldn't find an exact match."
        )

        user_prompt = f"System Context: {system_prompt}\n\nRelevant Products from Catalog:\n{context_str}\n\nUser Query: {message}\n\nPlease recommend the best products to the user based on their query."

        # 4. Generate the response using Google Gemini (Free Tier)
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        response = model.generate_content(user_prompt)
        ai_response = response.text

        return Response({
            'response': ai_response,
            'products': ProductSerializer(top_products, many=True, context={'request': request}).data
        })

    except Exception as e:
        return Response({'detail': f'Error generating response: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


