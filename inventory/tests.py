"""Tests for Phase A-F multi-shop refactor.

Covers: SalesTicket posting (IMMEDIATE / CREDIT / LAYBY), VAT math,
shop isolation, StockTransfer, Return reversal, Damaged GL posting,
DailyCashUp close-of-day.
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User

from inventory.models import (
    Inventory, Shop, ShopStock, StockTransfer, SalesTicket, SalesLine,
    Return as ReturnModel, Damaged, DailyCashUp, Customer, UserProfile,
)
from accounting.models import GLAccount, JournalEntry, CashbookEntry, ARInvoice, LaybyPlan
from accounting.utils import post_ticket


def _init_gl():
    """Seed the minimal GL accounts the tests need."""
    seeds = [
        ('1000', 'Cash on Hand', 'ASSET'),
        ('1010', 'EcoCash Float', 'ASSET'),
        ('1020', 'Bank Current Account', 'ASSET'),
        ('1200', 'Accounts Receivable', 'ASSET'),
        ('1300', 'Inventory', 'ASSET'),
        ('2300', 'Unearned Revenue', 'LIAB'),
        ('2400', 'Output VAT Payable', 'LIAB'),
        ('4000', 'Sales Revenue', 'INCOME'),
        ('5000', 'COGS', 'EXP'),
        ('5100', 'Inventory Loss', 'EXP'),
    ]
    for code, name, type_ in seeds:
        GLAccount.objects.get_or_create(code=code, defaults={'name': name, 'type': type_, 'is_active': True})


class PhaseABaseTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        _init_gl()
        cls.bby = Shop.objects.create(code='BBY', name='Baby Bazaar', is_active=True)
        cls.clo = Shop.objects.create(code='CLO', name='Clothing Shop', is_active=True)

        cls.cashier = User.objects.create_user(username='cashier1', password='x')
        UserProfile.objects.filter(user=cls.cashier).update(role='sales', can_make_sales=True, max_discount_percent=Decimal('50'))

        cls.customer = Customer.objects.create(
            name='Test Cust', phone='0771', credit_limit=Decimal('1000'), current_balance=Decimal('0'),
        )

        cls.product = Inventory.objects.create(
            product_code='TST-A', name='Test Product',
            purchase_price=Decimal('80'), selling_price=Decimal('115'),
        )

        cls.stock_bby = ShopStock.get_or_create_for(cls.bby, cls.product, None)
        cls.stock_bby.quantity = 100
        cls.stock_bby.save()

        cls.stock_clo = ShopStock.get_or_create_for(cls.clo, cls.product, None)
        cls.stock_clo.quantity = 50
        cls.stock_clo.save()

    def _make_ticket(self, shop, terms='IMMEDIATE', tender='CASH', qty=1, customer=None):
        ticket = SalesTicket.objects.create(
            shop=shop, cashier=self.cashier, terms=terms, tender_type=tender,
            customer=customer,
        )
        line = SalesLine(
            ticket=ticket, inventory_item=self.product, quantity=qty,
            unit_price_incl_vat=Decimal('115'), unit_cost=Decimal('80'),
        )
        line.compute(vat_rate=15)
        line.save()
        ticket.recalc_totals(save=True)
        return ticket


class VATMathTest(PhaseABaseTest):
    def test_vat_backout_from_inclusive_price(self):
        t = self._make_ticket(self.bby, qty=2)
        self.assertEqual(t.total_incl_vat, Decimal('230'))
        self.assertEqual(t.vat_total, Decimal('30.00'))
        self.assertEqual(t.subtotal_excl_vat, Decimal('200.00'))

    def test_vat_exempt_line_has_zero_vat(self):
        exempt = Inventory.objects.create(
            product_code='EX-1', name='Bread',
            selling_price=Decimal('50'), purchase_price=Decimal('30'),
            is_vat_exempt=True,
        )
        ShopStock.objects.filter(inventory_item=exempt, shop=self.bby).update(quantity=20)
        stock, _ = ShopStock.objects.get_or_create(inventory_item=exempt, shop=self.bby, variant=None, defaults={'quantity': 20})
        stock.quantity = 20
        stock.save()

        ticket = SalesTicket.objects.create(
            shop=self.bby, cashier=self.cashier, terms='IMMEDIATE', tender_type='CASH',
        )
        line = SalesLine(
            ticket=ticket, inventory_item=exempt, quantity=2,
            unit_price_incl_vat=Decimal('50'), is_vat_exempt=True, unit_cost=Decimal('30'),
        )
        line.compute(vat_rate=15)
        line.save()
        ticket.recalc_totals(save=True)
        self.assertEqual(ticket.vat_total, Decimal('0'))
        self.assertEqual(ticket.total_incl_vat, Decimal('100'))


class PostTicketImmediateTest(PhaseABaseTest):
    def test_cash_sale_posts_balanced_je_to_shop(self):
        t = self._make_ticket(self.bby, tender='CASH')
        post_ticket(t, user=self.cashier)

        je = JournalEntry.objects.filter(reference=t.receipt_number).first()
        self.assertIsNotNone(je)
        self.assertTrue(je.is_balanced)
        self.assertEqual(je.shop, self.bby)

        self.stock_bby.refresh_from_db()
        self.stock_clo.refresh_from_db()
        self.assertEqual(self.stock_bby.quantity, 99)
        self.assertEqual(self.stock_clo.quantity, 50)

    def test_ecocash_posts_to_1010(self):
        t = self._make_ticket(self.bby, tender='ECOCASH')
        post_ticket(t, user=self.cashier)
        je = JournalEntry.objects.filter(reference=t.receipt_number).first()
        ecocash_line = je.lines.filter(account__code='1010').first()
        self.assertIsNotNone(ecocash_line)
        self.assertEqual(ecocash_line.debit, Decimal('115'))

    def test_idempotency(self):
        t = self._make_ticket(self.bby)
        post_ticket(t, user=self.cashier)
        post_ticket(t, user=self.cashier)
        self.assertEqual(JournalEntry.objects.filter(reference=t.receipt_number).count(), 1)


class PostTicketCreditTest(PhaseABaseTest):
    def test_credit_sale_creates_ar_no_cashbook(self):
        t = self._make_ticket(self.clo, terms='CREDIT', customer=self.customer)
        post_ticket(t, user=self.cashier)

        ar = ARInvoice.objects.filter(ticket=t).first()
        self.assertIsNotNone(ar)
        self.assertEqual(ar.shop, self.clo)
        self.assertEqual(ar.total_amount, Decimal('115'))

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_balance, Decimal('115'))

        self.assertEqual(CashbookEntry.objects.filter(reference=t.receipt_number).count(), 0)

    def test_credit_limit_enforced(self):
        self.customer.credit_limit = Decimal('100')
        self.customer.save()
        t = self._make_ticket(self.clo, terms='CREDIT', customer=self.customer)
        with self.assertRaises(ValueError):
            post_ticket(t, user=self.cashier)


class PostTicketLaybyTest(PhaseABaseTest):
    def test_layby_creates_plan_and_mirrors_items(self):
        t = self._make_ticket(self.bby, terms='LAYBY', customer=self.customer, qty=2)
        post_ticket(t, user=self.cashier)

        plan = LaybyPlan.objects.filter(ticket=t).first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.shop, self.bby)
        self.assertEqual(plan.total_price, Decimal('230'))
        self.assertEqual(plan.items.count(), 1)

        self.stock_bby.refresh_from_db()
        self.assertEqual(self.stock_bby.quantity, 98)


class StockTransferTest(PhaseABaseTest):
    def test_transfer_moves_stock_and_writes_movements(self):
        t = StockTransfer.objects.create(
            from_shop=self.bby, to_shop=self.clo, inventory_item=self.product,
            quantity=10, transferred_by=self.cashier,
        )
        t.execute()

        self.stock_bby.refresh_from_db()
        self.stock_clo.refresh_from_db()
        self.assertEqual(self.stock_bby.quantity, 90)
        self.assertEqual(self.stock_clo.quantity, 60)
        self.assertEqual(t.status, 'COMPLETED')


class ReturnReversalTest(PhaseABaseTest):
    def test_partial_return_reverses_pro_rata(self):
        t = self._make_ticket(self.bby, tender='CASH', qty=3)
        post_ticket(t, user=self.cashier)

        line = t.lines.first()
        ret = ReturnModel(
            inventory_item=self.product, quantity_returned=1, reason='wrong size',
            ticket_line=line, refund_tender='CASH', is_restockable=True,
            approved_by=self.cashier,
        )
        ret.save()

        self.assertTrue(ret.posted_to_gl)
        self.assertEqual(ret.refund_amount, Decimal('115.00'))

        self.stock_bby.refresh_from_db()
        self.assertEqual(self.stock_bby.quantity, 98)


class DamagedGLTest(PhaseABaseTest):
    def test_damaged_posts_inventory_loss(self):
        d = Damaged.objects.create(
            inventory_item=self.product, quantity_damaged=2,
            damage_description='Dropped', shop=self.bby, recorded_by=self.cashier,
        )
        self.assertTrue(d.posted_to_gl)
        je = JournalEntry.objects.filter(reference=f'DMG-{d.pk}').first()
        self.assertIsNotNone(je)
        self.assertTrue(je.is_balanced)
        loss = je.lines.filter(account__code='5100').first()
        self.assertEqual(loss.debit, Decimal('160'))


class DailyCashUpTest(PhaseABaseTest):
    def test_close_day_sequential_z_numbers(self):
        import datetime
        today = datetime.date(2026, 4, 22)

        self.assertFalse(DailyCashUp.is_day_closed(self.bby, today))

        record = DailyCashUp.objects.create(
            shop=self.bby, date=today,
            z_number=DailyCashUp.next_z_number(self.bby),
            ticket_count=0,
        )
        self.assertEqual(record.z_number, 1)

        record2 = DailyCashUp.objects.create(
            shop=self.bby, date=datetime.date(2026, 4, 23),
            z_number=DailyCashUp.next_z_number(self.bby),
            ticket_count=0,
        )
        self.assertEqual(record2.z_number, 2)

        # CLO starts at 1 independently
        clo_rec = DailyCashUp.objects.create(
            shop=self.clo, date=today,
            z_number=DailyCashUp.next_z_number(self.clo),
            ticket_count=0,
        )
        self.assertEqual(clo_rec.z_number, 1)


class ShopIsolationTest(PhaseABaseTest):
    def test_per_shop_stock_is_independent(self):
        t = self._make_ticket(self.bby, qty=5)
        post_ticket(t)
        self.stock_bby.refresh_from_db()
        self.stock_clo.refresh_from_db()
        self.assertEqual(self.stock_bby.quantity, 95)
        self.assertEqual(self.stock_clo.quantity, 50)

    def test_ticket_carries_shop_fk_on_journal(self):
        t_bby = self._make_ticket(self.bby)
        post_ticket(t_bby)
        t_clo = self._make_ticket(self.clo)
        post_ticket(t_clo)

        je_bby = JournalEntry.objects.filter(reference=t_bby.receipt_number).first()
        je_clo = JournalEntry.objects.filter(reference=t_clo.receipt_number).first()
        self.assertEqual(je_bby.shop, self.bby)
        self.assertEqual(je_clo.shop, self.clo)
