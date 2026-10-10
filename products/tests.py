from django.test import TestCase
from django.contrib.auth import get_user_model
from decimal import Decimal
from products.models import (
    Category, Product, Order, OrderTimeline,
    RefundRequest, PaymentReconciliation, Earning
)

User = get_user_model()

class OrderManagementTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email='customer@example.com',
            password='password123',
            name='Test Customer',
            role='CUSTOMER'
        )
        self.seller = User.objects.create_user(
            email='seller@example.com',
            password='password123',
            name='Test Seller',
            role='HANDICRAFTER',
            is_approved=True
        )
        self.admin = User.objects.create_user(
            email='admin@example.com',
            password='password123',
            name='Test Admin',
            role='ADMIN',
            is_superuser=True
        )
        self.category = Category.objects.create(name='Woodcraft', slug='woodcraft')
        self.product = Product.objects.create(
            name='Handmade Bowl',
            seller=self.seller,
            category=self.category,
            price=Decimal('500.00'),
            stock=10,
            is_active=True,
            is_approved=True
        )

    def test_status_transitions_validation(self):
        """Test backend status transition state machine rules."""
        order = Order.objects.create(
            customer=self.customer,
            product=self.product,
            seller=self.seller,
            quantity=2,
            total_amount=Decimal('1000.00'),
            status='PENDING'
        )

        # Valid transition: PENDING -> PROCESSING
        allowed, msg = order.can_transition_to('PROCESSING', user=self.seller)
        self.assertTrue(allowed)

        # Invalid transition: PENDING -> DELIVERED (skipping processing/shipping)
        allowed, msg = order.can_transition_to('DELIVERED', user=self.seller)
        self.assertFalse(allowed)

        # Update order to DELIVERED
        order.status = 'DELIVERED'
        order.save()

        # Invalid transition: DELIVERED -> PROCESSING
        allowed, msg = order.can_transition_to('PROCESSING', user=self.seller)
        self.assertFalse(allowed)

        # Valid transition for customer: DELIVERED -> RETURN_REQUESTED
        allowed, msg = order.can_transition_to('RETURN_REQUESTED', user=self.customer)
        self.assertTrue(allowed)

        # Customer cannot mark delivered order as CANCELLED directly
        allowed, msg = order.can_transition_to('CANCELLED', user=self.customer)
        self.assertFalse(allowed)

    def test_cancellation_and_stock_restoration(self):
        """Test pre-shipment cancellation rules and stock restoration."""
        # Stock starts at 10, reduce 2 for order
        self.product.stock -= 2
        self.product.save()

        order = Order.objects.create(
            customer=self.customer,
            product=self.product,
            seller=self.seller,
            quantity=2,
            total_amount=Decimal('1000.00'),
            status='PROCESSING'
        )

        # Cancel order
        order.restore_stock()
        order.status = 'CANCELLED'
        order.cancellation_reason = 'Found a better price'
        order.save()

        # Product stock should be restored to 10
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertTrue(order.stock_restored)

        # Second restoration should be idempotent
        second_restore = order.restore_stock()
        self.assertFalse(second_restore)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_order_timeline_audit_logging(self):
        """Test chronological timeline generation."""
        order = Order.objects.create(
            customer=self.customer,
            product=self.product,
            seller=self.seller,
            quantity=1,
            total_amount=Decimal('500.00'),
            status='PENDING'
        )
        order.add_timeline('PENDING', 'Order Placed', 'Order placed by customer.', changed_by=self.customer)
        order.add_timeline('PROCESSING', 'Order Processing', 'Seller began handcrafting.', changed_by=self.seller)

        timeline = order.timeline.all()
        self.assertEqual(timeline.count(), 2)
        self.assertEqual(timeline[0].title, 'Order Placed')
        self.assertEqual(timeline[1].title, 'Order Processing')

    def test_refund_request_and_admin_approval(self):
        """Test refund request lifecycle and payment reconciliation."""
        order = Order.objects.create(
            customer=self.customer,
            product=self.product,
            seller=self.seller,
            quantity=1,
            total_amount=Decimal('500.00'),
            status='DELIVERED',
            is_paid=True,
            stripe_payment_intent='pi_test_123456'
        )

        # Create seller earning
        earning = Earning.objects.create(
            seller=self.seller,
            order=order,
            amount=Decimal('500.00'),
            commission=Decimal('50.00'),
            net_amount=Decimal('450.00'),
            status='PENDING'
        )

        # Customer creates refund request
        refund_req = RefundRequest.objects.create(
            order=order,
            customer=self.customer,
            reason='DEFECTIVE',
            explanation='Bowl arrived with a crack on the edge.',
            amount=Decimal('500.00'),
            status='PENDING'
        )

        # Admin approves refund request
        refund_req.status = 'APPROVED'
        refund_req.admin_notes = 'Verified damage photo. Full refund granted.'
        refund_req.decided_by = self.admin
        refund_req.save()

        # Reconcile payment
        recon = PaymentReconciliation.objects.create(
            order=order,
            refund_request=refund_req,
            payment_intent_id=order.stripe_payment_intent,
            refund_transaction_id='sim_ref_test_999',
            original_amount=order.total_amount,
            refunded_amount=refund_req.amount,
            gateway_status='SUCCEEDED',
            is_reconciled=True,
            reconciled_by=self.admin,
            notes='Reconciliation complete'
        )

        order.status = 'REFUNDED'
        order.save()
        earning.status = 'REFUNDED'
        earning.save()

        self.assertEqual(order.status, 'REFUNDED')
        self.assertEqual(earning.status, 'REFUNDED')
        self.assertEqual(recon.gateway_status, 'SUCCEEDED')
        self.assertTrue(recon.is_reconciled)

    def test_artisan_storefront(self):
        """Test public artisan storefront data and craft stories."""
        from products.models import SellerProfile, WorkshopPhoto
        profile, _ = SellerProfile.objects.get_or_create(
            user=self.seller,
            defaults={
                'bio': 'Passionate heritage woodworker from Kerala.',
                'craft_story': 'Learned the art of woodcarving from three generations of master crafters.',
                'craft_specialty': 'Teakwood & Rosewood Carving',
                'workshop_headline': 'Heritage Wood Studio, Calicut',
                'years_of_experience': 14,
                'techniques_used': 'Hand-chiseling, Natural Wax Polishing',
                'materials_used': 'Sustainable Teakwood, Natural Beeswax'
            }
        )

        response = self.client.get(f'/api/artisan/{self.seller.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['artisan']['name'], 'Test Seller')
        self.assertTrue(data['artisan']['is_verified'])
        self.assertEqual(len(data['products']), 1)
        self.assertEqual(data['products'][0]['name'], 'Handmade Bowl')
