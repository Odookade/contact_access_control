"""Standard business flows run by restricted users. Each test is skipped when the
corresponding application is not installed, run them on a database with
sale_management, purchase, account, crm and stock installed."""
from lxml import etree

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from .common import RESTRICTED, ContactAccessCommon


@tagged('post_install', '-at_install', 'contact_access', 'contact_access_flows')
class TestBusinessFlows(ContactAccessCommon):

    def require(self, *modules):
        installed = self.env['ir.module.module'].search_count(
            [('name', 'in', modules), ('state', '=', 'installed')])
        if installed != len(modules):
            self.skipTest(f"requires {', '.join(modules)}")

    def make_user(self, login, groups):
        return new_test_user(self.env, login, groups=','.join(['base.group_user', RESTRICTED] + groups))

    def product(self):
        return self.env['product.product'].create({
            'name': 'Widget', 'type': 'consu', 'list_price': 10, 'standard_price': 5})

    def test_sale_flow(self):
        self.require('sale')
        salesman = self.make_user('salesman', ['sales_team.group_sale_salesman'])
        self.grant(self.cat_customer, users=salesman, perm_write=True, perm_create=True)
        product = self.product()
        SaleOrder = self.env['sale.order'].with_user(salesman)
        with Form(SaleOrder) as order_form:
            order_form.partner_id = self.customer
            with order_form.order_line.new() as line:
                line.product_id = product
        order = order_form.save()
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        # quick-create a customer from the order field: gets the creatable category
        partner_id, _name = self.env['res.partner'].with_user(salesman).with_context(
            res_partner_search_mode='customer').name_create('Quick Customer')
        quick = self.env['res.partner'].browse(partner_id)
        self.assertEqual(quick.contact_category_ids, self.cat_customer)
        self.assertNotIn(self.installer, self.env['res.partner'].with_user(salesman).search([]))

    def test_sale_order_with_hidden_customer_stays_readable(self):
        self.require('sale')
        manager = self.make_user('salemanager', ['sales_team.group_sale_manager'])
        order = self.env['sale.order'].create({'partner_id': self.free.id})
        values = order.with_user(manager).web_read({'partner_id': {'fields': {'display_name': {}}}})
        self.assertEqual(values[0]['partner_id']['display_name'], 'Free Agent')

    def test_purchase_flow(self):
        self.require('purchase')
        vendor_cat = self.Category.create({'name': 'Vendors', 'assignment': 'rule',
                                           'domain': "[('supplier_rank', '>', 0)]"})
        vendor = self.env['res.partner'].create({'name': 'Vendor Inc', 'is_company': True, 'supplier_rank': 1})
        buyer = self.make_user('buyer', ['purchase.group_purchase_user'])
        self.grant(vendor_cat, users=buyer)
        self.assertEqual(self.visible(buyer, vendor | self.customer), vendor)
        product = self.product()
        order = self.env['purchase.order'].with_user(buyer).create({
            'partner_id': vendor.id,
            'order_line': [Command.create({'product_id': product.id, 'product_qty': 2, 'price_unit': 5})],
        })
        order.button_confirm()
        self.assertIn(order.state, ('purchase', 'done'))

    def test_invoice_flow(self):
        self.require('account')
        accountant = self.make_user('invoicer', ['account.group_account_invoice'])
        self.grant(self.cat_customer, users=accountant)
        self.env['account.journal'].search([('company_id', '=', self.env.company.id)], limit=1) or \
            self.skipTest("no chart of accounts")
        if not self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', self.env.company.id)]):
            self.skipTest("no sale journal")
        product = self.product()
        move = self.env['account.move'].with_user(accountant).create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({'product_id': product.id, 'quantity': 1, 'price_unit': 10})],
        })
        move.action_post()
        self.assertEqual(move.state, 'posted')
        self.assertGreater(self.customer.customer_rank, 0)

    def test_crm_convert_lead(self):
        self.require('crm')
        salesman = self.make_user('crmsalesman', ['sales_team.group_sale_salesman'])
        self.grant(self.cat_customer, users=salesman, perm_create=True, perm_write=True)
        lead = self.env['crm.lead'].with_user(salesman).create({
            'name': 'Opportunity', 'partner_name': 'Lead Company', 'contact_name': 'Lead Person',
            'email_from': 'lead@example.com', 'type': 'lead'})
        lead._handle_partner_assignment(create_missing=True)
        self.assertTrue(lead.partner_id)
        self.assertIn(self.cat_customer, lead.partner_id.commercial_partner_id.contact_category_ids)

    def test_stock_picking_flow(self):
        self.require('stock')
        stock_user = self.make_user('stockuser', ['stock.group_stock_user'])
        self.grant(self.cat_customer, users=stock_user)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        product = self.env['product.product'].create({'name': 'Stockable', 'is_storable': True})
        picking = self.env['stock.picking'].with_user(stock_user).create({
            'partner_id': self.customer.id,
            'picking_type_id': warehouse.out_type_id.id,
            'move_ids': [Command.create({
                'product_id': product.id, 'product_uom_qty': 1,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id})],
        })
        picking.action_confirm()
        self.assertEqual(picking.partner_id, self.customer)

    def test_field_filter_on_sale_partner(self):
        """Combination with a dynamic (check_company) client-side domain."""
        self.require('sale')
        field = self.env['ir.model.fields']._get('sale.order', 'partner_id')
        self.env['contact.field.filter'].create({
            'model_id': field.model_id.id, 'field_id': field.id,
            'category_ids': [Command.set(self.cat_customer.ids)], 'enforce': True})
        arch = self.env['sale.order'].get_views([(False, 'form')])['views']['form']['arch']
        domain_str = etree.fromstring(arch).xpath("//field[@name='partner_id']")[0].get('domain')
        self.assertIn('contact_category_ids', domain_str)
        self.assertIn('company_id', domain_str, "check_company domain is kept")
        domain = safe_eval(domain_str, {'company_id': self.env.company.id})
        found = self.env['res.partner'].search(domain)
        self.assertIn(self.customer, found)
        self.assertNotIn(self.installer, found)
        salesman = self.make_user('filtersalesman', ['sales_team.group_sale_salesman'])
        self.grant(self.cat_customer | self.cat_installer, users=salesman)
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(salesman).create({'partner_id': self.installer.id})
        self.env['sale.order'].with_user(salesman).create({'partner_id': self.customer.id})
