from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg, F
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model

import stripe
from .models import (
    Category, Product, Order, Review, Earning,
    CommissionSetting, Dispute, OrderTimeline,
    RefundRequest, PaymentReconciliation
)
from .admin_serializers import (
    AdminUserSerializer, AdminHandicrafterSerializer,
    AdminProductSerializer, AdminOrderSerializer,
    AdminReviewSerializer, AdminCategorySerializer,
    CommissionSettingSerializer, DisputeSerializer,
    AdminRefundRequestSerializer
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
        notes = request.data.get('notes', '')
        if not new_status or new_status not in dict(Order.STATUS_CHOICES):
            return Response({'detail': 'Invalid status provided.'}, status=400)

        # Validate status transition
        allowed, msg = order.can_transition_to(new_status, user=request.user)
        if not allowed:
            return Response({'detail': msg}, status=400)

        old_status = order.status
        order.status = new_status

        if new_status == 'CANCELLED':
            order.restore_stock()
            order.cancellation_reason = request.data.get('reason', 'Cancelled by administrator')
            order.cancelled_by = request.user
            order.cancelled_at = timezone.now()
            if hasattr(order, 'earning'):
                order.earning.status = 'CANCELLED'
                order.earning.save()

        elif new_status == 'RETURNED':
            order.restore_stock()
            if hasattr(order, 'earning'):
                order.earning.status = 'REFUNDED'
                order.earning.save()

        order.save()

        # Auto-create Earning record when order is delivered
        if new_status == 'DELIVERED':
            if not hasattr(order, 'earning'):
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
                    status='PENDING'
                )

        # Timeline event
        order.add_timeline(
            status=new_status,
            title=f"Order {new_status.replace('_', ' ').title()} by Admin",
            notes=notes or f"Administrator updated order status from {old_status} to {new_status}.",
            changed_by=request.user
        )

        serializer = AdminOrderSerializer(order, context={'request': request})
        return Response(serializer.data)
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found.'}, status=404)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_refund_order(request, pk):
    """Admin direct refund endpoint with payment reconciliation and stock restoration."""
    try:
        order = Order.objects.get(id=pk)
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found.'}, status=404)

    restore_stock = request.data.get('restore_stock', True)
    admin_notes = request.data.get('admin_notes', 'Refund issued by administrator')
    refund_amount = request.data.get('amount')
    try:
        refund_amount = float(refund_amount) if refund_amount is not None else float(order.total_amount)
    except (ValueError, TypeError):
        refund_amount = float(order.total_amount)

    # Validate transition
    allowed, msg = order.can_transition_to('REFUNDED', user=request.user)
    if not allowed and order.status != 'CANCELLED':
        return Response({'detail': msg}, status=400)

    # Stock restoration
    if restore_stock:
        order.restore_stock()

    # Reconcile Payment (Stripe refund)
    refund_id = f"sim_ref_{order.id}_{int(timezone.now().timestamp())}"
    gateway_status = 'SUCCEEDED'
    if order.stripe_payment_intent:
        try:
            stripe_ref = stripe.Refund.create(
                payment_intent=order.stripe_payment_intent,
                amount=int(refund_amount * 100)
            )
            refund_id = stripe_ref.id
        except Exception as se:
            print(f"Stripe refund API call: {se}")
            gateway_status = 'SIMULATED'

    PaymentReconciliation.objects.create(
        order=order,
        payment_intent_id=order.stripe_payment_intent,
        refund_transaction_id=refund_id,
        original_amount=order.total_amount,
        refunded_amount=refund_amount,
        gateway_status=gateway_status,
        is_reconciled=True,
        reconciled_by=request.user,
        notes=admin_notes
    )

    order.status = 'REFUNDED'
    order.save()

    # Reverse seller earning
    if hasattr(order, 'earning'):
        order.earning.status = 'REFUNDED'
        order.earning.save()

    # Mark any pending RefundRequest approved
    pending_reqs = order.refund_requests.filter(status='PENDING')
    for req in pending_reqs:
        req.status = 'APPROVED'
        req.admin_notes = admin_notes
        req.decided_by = request.user
        req.decided_at = timezone.now()
        req.save()

    order.add_timeline(
        status='REFUNDED',
        title='Refund Processed & Reconciled',
        notes=f"Admin issued ₹{refund_amount} refund ({gateway_status}). Stock restored: {'Yes' if restore_stock else 'No'}. Notes: {admin_notes}",
        changed_by=request.user
    )

    serializer = AdminOrderSerializer(order, context={'request': request})
    return Response({
        'detail': f'Order #{pk} successfully refunded and reconciled.',
        'order': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_refund_requests(request):
    """List refund requests for admin review."""
    status_filter = request.query_params.get('status', '')
    qs = RefundRequest.objects.select_related('order', 'customer', 'decided_by', 'order__product', 'order__seller')
    if status_filter:
        qs = qs.filter(status=status_filter.upper())
    serializer = AdminRefundRequestSerializer(qs, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@admin_required
def admin_decide_refund_request(request, pk):
    """Admin decision (APPROVE or REJECT) on a customer refund request."""
    try:
        refund_req = RefundRequest.objects.select_related('order', 'customer').get(id=pk)
    except RefundRequest.DoesNotExist:
        return Response({'detail': 'Refund request not found.'}, status=404)

    decision = request.data.get('decision', '').upper()
    admin_notes = request.data.get('admin_notes', '').strip()
    restore_stock = request.data.get('restore_stock', True)

    if decision not in ['APPROVE', 'REJECT']:
        return Response({'detail': 'Decision must be either APPROVE or REJECT.'}, status=400)

    order = refund_req.order

    if decision == 'APPROVE':
        refund_amount = request.data.get('amount')
        try:
            refund_amount = float(refund_amount) if refund_amount is not None else float(refund_req.amount)
        except (ValueError, TypeError):
            refund_amount = float(refund_req.amount)

        if restore_stock:
            order.restore_stock()

        # Reconcile Payment
        refund_id = f"sim_ref_{order.id}_{int(timezone.now().timestamp())}"
        gateway_status = 'SUCCEEDED'
        if order.stripe_payment_intent:
            try:
                stripe_ref = stripe.Refund.create(
                    payment_intent=order.stripe_payment_intent,
                    amount=int(refund_amount * 100)
                )
                refund_id = stripe_ref.id
            except Exception as se:
                print(f"Stripe refund exception: {se}")
                gateway_status = 'SIMULATED'

        PaymentReconciliation.objects.create(
            order=order,
            refund_request=refund_req,
            payment_intent_id=order.stripe_payment_intent,
            refund_transaction_id=refund_id,
            original_amount=order.total_amount,
            refunded_amount=refund_amount,
            gateway_status=gateway_status,
            is_reconciled=True,
            reconciled_by=request.user,
            notes=admin_notes or 'Refund request approved by admin.'
        )

        order.status = 'REFUNDED'
        order.save()

        if hasattr(order, 'earning'):
            order.earning.status = 'REFUNDED'
            order.earning.save()

        refund_req.status = 'APPROVED'
        refund_req.admin_notes = admin_notes
        refund_req.decided_by = request.user
        refund_req.decided_at = timezone.now()
        refund_req.save()

        order.add_timeline(
            status='REFUNDED',
            title='Refund Request Approved',
            notes=f"Admin approved refund request of ₹{refund_amount} ({gateway_status}). Stock restored: {'Yes' if restore_stock else 'No'}. Notes: {admin_notes}",
            changed_by=request.user
        )

        return Response({
            'detail': f'Refund request #{pk} approved. ₹{refund_amount} refunded.',
            'refund_request': AdminRefundRequestSerializer(refund_req).data
        })

    else: # REJECT
        if not admin_notes:
            return Response({'detail': 'Please provide an admin note explaining the rejection reason.'}, status=400)

        refund_req.status = 'REJECTED'
        refund_req.admin_notes = admin_notes
        refund_req.decided_by = request.user
        refund_req.decided_at = timezone.now()
        refund_req.save()

        order.add_timeline(
            status=order.status,
            title='Refund Request Rejected',
            notes=f"Admin rejected refund request: {admin_notes}",
            changed_by=request.user
        )

        return Response({
            'detail': f'Refund request #{pk} rejected.',
            'refund_request': AdminRefundRequestSerializer(refund_req).data
        })


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
