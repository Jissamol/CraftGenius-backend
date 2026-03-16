import stripe
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Product, Order
import os

stripe.api_key = settings.STRIPE_SECRET_KEY

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    """
    Creates a Stripe Checkout Session.
    If 'product_id' is provided, it's a 'Buy Now' for a single item.
    Otherwise, it processes the entire Cart.
    """
    product_id = request.data.get('product_id')
    quantity = int(request.data.get('quantity', 1))
    
    base_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    line_items = []
    metadata = {'user_id': str(request.user.id)}

    try:
        if product_id:
            # Single item "Buy Now"
            product = Product.objects.get(id=product_id, is_active=True)
            line_items.append({
                'price_data': {
                    'currency': 'inr',
                    'product_data': {
                        'name': product.name,
                        'description': product.description[:100],
                    },
                    'unit_amount': int(product.price * 100),
                },
                'quantity': quantity,
            })
            metadata['type'] = 'single'
            metadata['product_id'] = str(product.id)
            metadata['quantity'] = str(quantity)
        else:
            # Cart checkout
            from .models import Cart
            cart = Cart.objects.get(user=request.user)
            items = cart.items.all()
            if not items.exists():
                return Response({'error': 'Cart is empty'}, status=400)
            
            for item in items:
                line_items.append({
                    'price_data': {
                        'currency': 'inr',
                        'product_data': {
                            'name': item.product.name,
                        },
                        'unit_amount': int(item.product.price * 100),
                    },
                    'quantity': item.quantity,
                })
            metadata['type'] = 'cart'
            metadata['cart_id'] = str(cart.id)

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=f"{base_url}/customer/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/customer/payment-cancel",
            metadata=metadata
        )

        # Create PENDING orders in DB immediately
        if product_id:
            Order.objects.create(
                customer=request.user,
                product=product,
                seller=product.seller,
                quantity=quantity,
                total_amount=(product.price * quantity),
                status='PENDING',
                is_paid=False,
                stripe_session_id=checkout_session.id
            )
        else:
            # Re-read cart items to create orders
            from .models import Cart
            cart = Cart.objects.get(user=request.user)
            for item in cart.items.all():
                Order.objects.create(
                    customer=request.user,
                    product=item.product,
                    seller=item.product.seller,
                    quantity=item.quantity,
                    total_amount=(item.product.price * item.quantity),
                    status='PENDING',
                    is_paid=False,
                    stripe_session_id=checkout_session.id
                )
            # We DON'T clear the cart yet. We clear it in the webhook or on success page confirmation.

        return Response({'url': checkout_session.url, 'id': checkout_session.id})

    except (Product.DoesNotExist, Exception) as e:
        print(f"Stripe Session Error: {e}")
        return Response({'error': str(e)}, status=400)


@csrf_exempt
def stripe_webhook(request):
    """
    Secure endpoint for Stripe webhooks.
    Verifies signature and updates order status.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return HttpResponse(status=400)

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = getattr(session, 'metadata', {})
        user_id = getattr(metadata, 'user_id', None)
        session_id = getattr(session, 'id', None)
        payment_intent = getattr(session, 'payment_intent', None)

        try:
            # Find all pending orders for this session
            orders = Order.objects.filter(stripe_session_id=session_id)
            
            for order in orders:
                order.is_paid = True
                order.status = 'PROCESSING'
                order.stripe_payment_intent = payment_intent
                order.save()
                
                # Reduce stock
                product = order.product
                product.stock -= order.quantity
                product.save()

            # If it was a cart checkout, clear the cart
            if getattr(metadata, 'type', None) == 'cart':
                from .models import Cart
                Cart.objects.get(user_id=user_id).items.all().delete()
                
        except Exception as e:
            print(f"Error processing webhook for session {session_id}: {e}")

    return HttpResponse(status=200)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_success_view(request):
    """Confirm payment status for the frontend with a fallback check."""
    session_id = request.query_params.get('session_id')
    if not session_id:
        return Response({'error': 'No session ID provided'}, status=400)
    
    orders = Order.objects.filter(stripe_session_id=session_id, customer=request.user)
    
    # Fallback: Check Stripe session status directly if webhook is slow
    if orders.exists() and not orders.filter(is_paid=True).exists():
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid':
                for order in orders:
                    order.is_paid = True
                    order.status = 'PROCESSING'
                    order.stripe_payment_intent = session.payment_intent
                    order.save()
                    
                    # Stock reduction (atomicity check)
                    product = order.product
                    product.stock -= order.quantity
                    product.save()
                
                # Clear cart if it was a cart checkout
                if getattr(session.metadata, 'type', None) == 'cart':
                    from .models import Cart
                    Cart.objects.get(user=request.user).items.all().delete()
        except Exception as e:
            print(f"Fallback check failed: {e}")

    orders = Order.objects.filter(stripe_session_id=session_id, customer=request.user)
    if not orders.filter(is_paid=True).exists():
        return Response({'status': 'pending', 'message': 'Payment processing...'})
    
    return Response({
        'status': 'success',
        'orders': [{'id': o.id, 'product': o.product.name} for o in orders]
    })
