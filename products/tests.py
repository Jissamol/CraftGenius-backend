from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from decimal import Decimal
from products.models import (
    Category, Product, Order, OrderTimeline,
    RefundRequest, PaymentReconciliation, Earning,
    SellerPayout, SellerLedgerEntry,
    AdminAuditLog, PlatformMonitoringLog, CommissionSetting
)

User = get_user_model()

class OrderManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
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

    def test_transaction_ledger_and_transparent_earnings(self):
        """Test transaction ledger tracking, running balance, and transparent earnings breakdown."""
        order = Order.objects.create(
            customer=self.customer,
            product=self.product,
            seller=self.seller,
            quantity=2,
            total_amount=Decimal('1000.00'),
            status='PROCESSING',
            is_paid=True,
            stripe_payment_intent='pi_ledger_test_100'
        )

        # Record Gross Sale in ledger
        entry_sale = SellerLedgerEntry.record(
            seller=self.seller,
            entry_type='SALE',
            amount=Decimal('1000.00'),
            is_credit=True,
            description="Gross Sale for Order #1",
            order=order,
            reference_id='pi_ledger_test_100'
        )
        self.assertEqual(entry_sale.balance_after, Decimal('1000.00'))

        # Record Platform Commission (10%)
        entry_comm = SellerLedgerEntry.record(
            seller=self.seller,
            entry_type='COMMISSION',
            amount=Decimal('100.00'),
            is_credit=False,
            description="Platform Commission (10%) for Order #1",
            order=order,
            reference_id='pi_ledger_test_100'
        )
        self.assertEqual(entry_comm.balance_after, Decimal('900.00'))

        # Authenticate seller and check GET /api/seller/earnings/
        self.client.force_authenticate(user=self.seller)
        response = self.client.get('/api/seller/earnings/')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data['gross_sales'], 1000.0)
        self.assertEqual(data['total_commission'], 100.0)
        self.assertEqual(data['total_refunds'], 0.0)
        self.assertEqual(data['net_earnings'], 900.0)
        self.assertEqual(data['available_balance'], 900.0)
        self.assertEqual(len(data['ledger_entries']), 2)

    def test_payout_request_and_admin_processing(self):
        """Test seller payout request, balance reservation, and admin payout processing."""
        # Seed ledger with 1500 net balance
        SellerLedgerEntry.record(
            seller=self.seller,
            entry_type='SALE',
            amount=Decimal('1500.00'),
            is_credit=True,
            description="Sale initial balance"
        )

        self.client.force_authenticate(user=self.seller)
        
        # 1. Attempt to withdraw more than available balance (should fail)
        res_fail = self.client.post('/api/seller/payouts/request/', {
            'amount': '2000.00',
            'payout_method': 'BANK_TRANSFER',
            'account_details': 'HDFC0001, A/C: 123456'
        })
        self.assertEqual(res_fail.status_code, 400)

        # 2. Withdraw valid amount
        res_req = self.client.post('/api/seller/payouts/request/', {
            'amount': '500.00',
            'payout_method': 'BANK_TRANSFER',
            'account_details': 'HDFC0001, A/C: 123456',
            'notes': 'Monthly payout'
        })
        self.assertEqual(res_req.status_code, 201)
        payout_id = res_req.json()['payout']['id']

        # Available balance should now be 1500 - 500 = 1000
        res_earn = self.client.get('/api/seller/earnings/')
        self.assertEqual(res_earn.json()['available_balance'], 1000.0)
        self.assertEqual(res_earn.json()['pending_payouts'], 500.0)

        # 3. Admin approves payout
        self.client.force_authenticate(user=self.admin)
        res_approve = self.client.post(f'/api/admin/payouts/{payout_id}/process/', {
            'action': 'APPROVE',
            'reference_id': 'UTR_TEST_12345678'
        })
        self.assertEqual(res_approve.status_code, 200)
        self.assertEqual(res_approve.json()['payout']['status'], 'PAID')

        # Verify payout ledger entry was recorded and balance updated
        payout_entry = SellerLedgerEntry.objects.filter(payout_id=payout_id, entry_type='PAYOUT').first()
        self.assertIsNotNone(payout_entry)
        self.assertEqual(payout_entry.amount, Decimal('500.00'))
        self.assertFalse(payout_entry.is_credit)
        self.assertEqual(payout_entry.balance_after, Decimal('1000.00'))


class AdminAuditAndMonitoringTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email='superadmin@example.com',
            password='password123',
            name='Master Admin',
            role='ADMIN',
            is_superuser=True
        )
        self.seller = User.objects.create_user(
            email='artisan_cand@example.com',
            password='password123',
            name='Candidate Artisan',
            role='HANDICRAFTER',
            is_approved=False
        )
        self.category = Category.objects.create(name='Clay & Ceramics', slug='clay-ceramics')
        self.product = Product.objects.create(
            name='Handmade Pot',
            seller=self.seller,
            category=self.category,
            price=Decimal('250.00'),
            stock=5,
            is_approved=False
        )
        self.client.force_authenticate(user=self.admin)

    def test_seller_approval_audit_log(self):
        """Admin approving handicrafter writes to AdminAuditLog."""
        res = self.client.put(f'/api/admin/handicrafters/{self.seller.id}/approve/')
        self.assertEqual(res.status_code, 200)

        log = AdminAuditLog.objects.filter(
            action_type='SELLER_APPROVAL',
            target_id=str(self.seller.id)
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.admin, self.admin)
        self.assertEqual(log.details.get('decision'), 'APPROVED')

    def test_product_moderation_audit_log(self):
        """Admin approving product writes to AdminAuditLog."""
        res = self.client.put(f'/api/admin/products/{self.product.id}/approve/')
        self.assertEqual(res.status_code, 200)

        log = AdminAuditLog.objects.filter(
            action_type='PRODUCT_MODERATION',
            target_id=str(self.product.id)
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details.get('decision'), 'APPROVED')

    def test_commission_change_audit_log(self):
        """Admin changing commission rate records before and after values in audit log."""
        CommissionSetting.objects.update_or_create(id=1, defaults={'percentage': Decimal('10.00')})

        res = self.client.put('/api/admin/commission/', {'percentage': 12.50}, format='json')
        self.assertEqual(res.status_code, 200)

        log = AdminAuditLog.objects.filter(action_type='COMMISSION_CHANGE').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details.get('new_rate'), 12.50)
        self.assertEqual(log.details.get('previous_rate'), 10.00)

    def test_platform_monitoring_incident_and_resolve(self):
        """Platform error log creation and administrative resolution."""
        incident = PlatformMonitoringLog.record(
            log_type='PAYMENT_FAILURE',
            severity='WARNING',
            source='STRIPE_CHECKOUT',
            event_id='evt_test_failed_123',
            customer_email='buyer@example.com',
            error_message='Payment method card_declined by issuer.',
            payload={'decline_code': 'insufficient_funds'}
        )
        self.assertFalse(incident.is_resolved)

        # Query monitoring summary & logs
        res = self.client.get('/api/admin/monitoring/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['health_summary']['total_events'], 1)
        self.assertEqual(res.json()['health_summary']['unresolved_count'], 1)

        # Resolve incident
        resolve_res = self.client.post(
            f'/api/admin/monitoring/{incident.id}/resolve/',
            {'notes': 'Customer re-attempted with alternate card successfully.'},
            format='json'
        )
        self.assertEqual(resolve_res.status_code, 200)
        incident.refresh_from_db()
        self.assertTrue(incident.is_resolved)
        self.assertEqual(incident.resolved_by, self.admin)

        # Check that resolution was also recorded into the admin audit log
        res_audit = self.client.get('/api/admin/audit-logs/')
        self.assertEqual(res_audit.status_code, 200)
        logs = res_audit.json()['logs']
        self.assertTrue(any('Resolved monitoring incident' in r['action_summary'] for r in logs))

