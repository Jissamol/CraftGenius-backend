from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg, F
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

from .models import (
    Category, Product, Order, Review, Earning,
    CommissionSetting, Dispute
)
from .admin_serializers import (
    AdminUserSerializer, AdminHandicrafterSerializer,
    AdminProductSerializer, AdminOrderSerializer,
    AdminReviewSerializer, AdminCategorySerializer,
    CommissionSettingSerializer, DisputeSerializer
)

User = get_user_model()


def is_admin(user):
    return user.role == 'ADMIN' or user.is_superuser


def admin_required(func):
    """Decorator to enforce admin-only access."""
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            return Response(
                {'detail': 'Admin access required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        return func(request, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ─────────────────── Dashboard ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_dashboard(request):
    total_users = User.objects.count()
    total_customers = User.objects.filter(role='CUSTOMER').count()
    total_handicrafters = User.objects.filter(role='HANDICRAFTER').count()
    pending_approvals = User.objects.filter(role='HANDICRAFTER', is_approved=False).count()
    total_products = Product.objects.count()
    total_orders = Order.objects.count()
    total_revenue = Order.objects.filter(
        status='DELIVERED'
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    total_commission = Earning.objects.aggregate(
        total=Sum('commission')
    )['total'] or 0

    # Recent activity
    recent_orders = Order.objects.order_by('-created_at')[:5]
    recent_users = User.objects.order_by('-created_at')[:5]

    # Top categories
    top_categories = Category.objects.annotate(
        product_count=Count('products'),
        order_count=Count('products__orders')
    ).order_by('-order_count')[:6]

    return Response({
        'total_users': total_users,
        'total_customers': total_customers,
        'total_handicrafters': total_handicrafters,
        'pending_approvals': pending_approvals,
        'total_products': total_products,
        'total_orders': total_orders,
        'total_revenue': float(total_revenue),
        'total_commission': float(total_commission),
        'recent_orders': [
            {
                'id': o.id,
                'product_name': o.product.name,
                'customer_name': o.customer.name,
                'total_amount': float(o.total_amount),
                'status': o.status,
                'created_at': o.created_at.isoformat()
            } for o in recent_orders
        ],
        'recent_users': [
            {
                'id': u.id,
                'name': u.name,
                'email': u.email,
                'role': u.role,
                'created_at': u.created_at.isoformat()
            } for u in recent_users
        ],
        'top_categories': [
            {
                'name': c.name,
                'product_count': c.product_count,
                'order_count': c.order_count
            } for c in top_categories
        ],
        'fraud_alerts': Order.objects.filter(
            total_amount__gte=10000, status='PENDING'
        ).count()
    })


# ─────────────────── Analytics ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_analytics(request):
    period = request.query_params.get('period', '30d')
    days_map = {'7d': 7, '30d': 30, '6m': 180, '1y': 365}
    days = days_map.get(period, 30)
    start_date = timezone.now() - timedelta(days=days)

    # Revenue over time
    if days <= 30:
        revenue_data = Order.objects.filter(
            created_at__gte=start_date, status='DELIVERED'
        ).annotate(date=TruncDate('created_at')).values('date').annotate(
            revenue=Sum('total_amount'), orders=Count('id')
        ).order_by('date')
    else:
        revenue_data = Order.objects.filter(
            created_at__gte=start_date, status='DELIVERED'
        ).annotate(date=TruncMonth('created_at')).values('date').annotate(
            revenue=Sum('total_amount'), orders=Count('id')
        ).order_by('date')

    # User growth
    user_growth = User.objects.filter(
        created_at__gte=start_date
    ).annotate(date=TruncDate('created_at')).values('date').annotate(
        count=Count('id')
    ).order_by('date')

    # Daily orders
    daily_orders = Order.objects.filter(
        created_at__gte=start_date
    ).annotate(date=TruncDate('created_at')).values('date').annotate(
        count=Count('id')
    ).order_by('date')

    # Seller performance
    seller_perf = User.objects.filter(role='HANDICRAFTER').annotate(
        total_sales=Sum('seller_orders__total_amount'),
        order_count=Count('seller_orders')
    ).order_by('-total_sales')[:10]

    # Category distribution
    cat_dist = Category.objects.annotate(
        total_sales=Sum('products__orders__total_amount')
    ).order_by('-total_sales')[:8]

    return Response({
        'revenue_data': [
            {
                'date': d['date'].isoformat() if d['date'] else '',
                'revenue': float(d['revenue'] or 0),
                'orders': d['orders']
            } for d in revenue_data
        ],
        'user_growth': [
            {'date': d['date'].isoformat() if d['date'] else '', 'count': d['count']}
            for d in user_growth
        ],
        'daily_orders': [
            {'date': d['date'].isoformat() if d['date'] else '', 'count': d['count']}
            for d in daily_orders
        ],
        'seller_performance': [
            {
                'name': s.name,
                'total_sales': float(s.total_sales or 0),
                'order_count': s.order_count
            } for s in seller_perf
        ],
        'category_distribution': [
            {'name': c.name, 'sales': float(c.total_sales or 0)}
            for c in cat_dist
        ]
    })


# ─────────────────── Handicrafters ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_handicrafters(request):
    filter_type = request.query_params.get('filter', 'all')
    qs = User.objects.filter(role='HANDICRAFTER')
    if filter_type == 'pending':
        qs = qs.filter(is_approved=False)
    elif filter_type == 'approved':
        qs = qs.filter(is_approved=True)
    serializer = AdminHandicrafterSerializer(qs.order_by('-created_at'), many=True)
    return Response(serializer.data)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_approve_handicrafter(request, pk):
    try:
        user = User.objects.get(id=pk, role='HANDICRAFTER')
        user.is_approved = True
        user.save()
        return Response({'detail': f'{user.name} approved successfully.'})
    except User.DoesNotExist:
        return Response({'detail': 'Handicrafter not found.'}, status=404)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_reject_handicrafter(request, pk):
    try:
        user = User.objects.get(id=pk, role='HANDICRAFTER')
        reason = request.data.get('reason', '')
        user.is_approved = False
        user.is_active = False
        user.save()
        return Response({'detail': f'{user.name} rejected.', 'reason': reason})
    except User.DoesNotExist:
        return Response({'detail': 'Handicrafter not found.'}, status=404)


# ─────────────────── Products ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_products(request):
    filter_type = request.query_params.get('filter', 'all')
    qs = Product.objects.select_related('seller', 'category')
    if filter_type == 'pending':
        qs = qs.filter(is_approved=False)
    elif filter_type == 'approved':
        qs = qs.filter(is_approved=True)
    serializer = AdminProductSerializer(qs, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_approve_product(request, pk):
    try:
        product = Product.objects.get(id=pk)
        product.is_approved = True
        product.save()
        return Response({'detail': f'{product.name} approved.'})
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found.'}, status=404)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_reject_product(request, pk):
    try:
        product = Product.objects.get(id=pk)
        product.is_approved = False
        product.save()
        return Response({'detail': f'{product.name} rejected.'})
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found.'}, status=404)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_delete_product(request, pk):
    try:
        product = Product.objects.get(id=pk)
        name = product.name
        product.delete()
        return Response({'detail': f'{name} deleted.'})
    except Product.DoesNotExist:
        return Response({'detail': 'Product not found.'}, status=404)


# ─────────────────── Orders ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_orders(request):
    filter_status = request.query_params.get('status', '')
    qs = Order.objects.select_related('customer', 'seller', 'product')
    if filter_status:
        qs = qs.filter(status=filter_status)
    serializer = AdminOrderSerializer(qs, many=True, context={'request': request})
    return Response(serializer.data)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_update_order_status(request, pk):
    try:
        order = Order.objects.get(id=pk)
        new_status = request.data.get('status')
        if new_status and new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            order.save()

            # Auto-create Earning record when order is delivered
            if new_status == 'DELIVERED' and not hasattr(order, 'earning'):
                commission_rate = CommissionSetting.get_rate()
                amount = order.total_amount
                commission = round(float(amount) * float(commission_rate) / 100, 2)
                net_amount = float(amount) - commission
                Earning.objects.create(
                    seller=order.seller,
                    order=order,
                    amount=amount,
                    commission=commission,
                    net_amount=net_amount,
                )

            return Response({'detail': f'Order #{pk} status updated to {new_status}.'})
        return Response({'detail': 'Invalid status.'}, status=400)
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found.'}, status=404)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_refund_order(request, pk):
    try:
        order = Order.objects.get(id=pk)
        order.status = 'CANCELLED'
        order.save()
        # Restore stock
        order.product.stock += order.quantity
        order.product.save()
        return Response({'detail': f'Order #{pk} refunded and cancelled.'})
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found.'}, status=404)


# ─────────────────── Customers ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_customers(request):
    qs = User.objects.filter(role='CUSTOMER').order_by('-created_at')
    serializer = AdminUserSerializer(qs, many=True)
    return Response(serializer.data)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_toggle_customer(request, pk):
    try:
        user = User.objects.get(id=pk, role='CUSTOMER')
        user.is_active = not user.is_active
        user.save()
        action = 'reactivated' if user.is_active else 'suspended'
        return Response({'detail': f'{user.name} {action}.', 'is_active': user.is_active})
    except User.DoesNotExist:
        return Response({'detail': 'Customer not found.'}, status=404)


# ─────────────────── Categories ───────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_categories(request):
    if request.method == 'GET':
        cats = Category.objects.all()
        serializer = AdminCategorySerializer(cats, many=True)
        return Response(serializer.data)
    else:
        serializer = AdminCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_category_detail(request, pk):
    try:
        cat = Category.objects.get(id=pk)
    except Category.DoesNotExist:
        return Response({'detail': 'Category not found.'}, status=404)

    if request.method == 'DELETE':
        cat.delete()
        return Response({'detail': 'Category deleted.'})
    else:
        serializer = AdminCategorySerializer(cat, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


# ─────────────────── Reviews ───────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_reviews(request):
    qs = Review.objects.select_related('product', 'customer', 'product__seller')
    serializer = AdminReviewSerializer(qs, many=True)
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_delete_review(request, pk):
    try:
        review = Review.objects.get(id=pk)
        review.delete()
        return Response({'detail': 'Review deleted.'})
    except Review.DoesNotExist:
        return Response({'detail': 'Review not found.'}, status=404)


# ─────────────────── Disputes ───────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_disputes(request):
    if request.method == 'GET':
        filter_status = request.query_params.get('status', '')
        qs = Dispute.objects.select_related('order', 'raised_by', 'order__product', 'order__customer', 'order__seller')
        if filter_status:
            qs = qs.filter(status=filter_status)
        serializer = DisputeSerializer(qs, many=True)
        return Response(serializer.data)
    else:
        serializer = DisputeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(raised_by=request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_update_dispute(request, pk):
    try:
        dispute = Dispute.objects.get(id=pk)
        new_status = request.data.get('status', dispute.status)
        resolution = request.data.get('resolution', dispute.resolution)
        dispute.status = new_status
        dispute.resolution = resolution
        dispute.save()
        serializer = DisputeSerializer(dispute)
        return Response(serializer.data)
    except Dispute.DoesNotExist:
        return Response({'detail': 'Dispute not found.'}, status=404)


# ─────────────────── Commission ───────────────────

@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_commission(request):
    setting, _ = CommissionSetting.objects.get_or_create(
        pk=1, defaults={'percentage': 10.00}
    )

    if request.method == 'GET':
        # Per-seller breakdown
        sellers = User.objects.filter(role='HANDICRAFTER', is_approved=True).annotate(
            total_sales=Sum('earnings__amount'),
            total_commission=Sum('earnings__commission'),
            total_net=Sum('earnings__net_amount')
        ).order_by('-total_sales')[:20]

        return Response({
            'commission': CommissionSettingSerializer(setting).data,
            'seller_breakdown': [
                {
                    'id': s.id,
                    'name': s.name,
                    'total_sales': float(s.total_sales or 0),
                    'total_commission': float(s.total_commission or 0),
                    'total_net': float(s.total_net or 0)
                } for s in sellers
            ]
        })
    else:
        percentage = request.data.get('percentage')
        if percentage is not None:
            setting.percentage = percentage
            setting.updated_by = request.user
            setting.save()
            return Response(CommissionSettingSerializer(setting).data)
        return Response({'detail': 'Percentage is required.'}, status=400)
