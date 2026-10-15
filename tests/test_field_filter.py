from lxml import etree

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import ContactAccessCommon


@tagged('post_install', '-at_install', 'contact_access')
class TestFieldFilter(ContactAccessCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parent_field = cls.env['ir.model.fields']._get('res.partner', 'parent_id')
        cls.user_field = cls.env['ir.model.fields']._get('res.partner', 'user_id')
        cls.sales_group = cls.env['res.groups'].create({'name': 'Sellers'})
        cls.seller = cls.env['res.users'].create({
            'name': 'Seller', 'login': 'seller', 'group_ids': [Command.set(
                (cls.env.ref('base.group_user') | cls.sales_group).ids)]})

    def make_filter(self, field, **vals):
        return self.env['contact.field.filter'].create({
            'model_id': field.model_id.id, 'field_id': field.id, **vals})

    def field_domain(self, model, fname, view_type='form'):
        arch = self.env[model].get_views([(False, view_type)])['views'][view_type]['arch']
        node = etree.fromstring(arch).xpath(f"//field[@name='{fname}']")[0]
        return node.get('domain')

    def test_domain_injected_and_combined(self):
        original = self.field_domain('res.partner', 'parent_id')
        flt = self.make_filter(self.parent_field, category_ids=[Command.set(self.cat_customer.ids)])
        domain_str = self.field_domain('res.partner', 'parent_id')
        self.assertIn('contact_category_ids', domain_str)
        self.assertIn(original, domain_str, "the view's own domain is kept (AND)")
        domain = safe_eval(domain_str)
        found = self.env['res.partner'].search(domain)
        self.assertIn(self.customer, found)
        self.assertNotIn(self.installer, found)
        self.assertNotIn(self.customer_child, found, "original is_company domain still applies")
        # archiving the filter removes the injection (cache invalidated)
        flt.active = False
        self.assertEqual(self.field_domain('res.partner', 'parent_id'), original)

    def test_category_change_updates_views(self):
        self.make_filter(self.parent_field, category_ids=[Command.set(self.cat_rule.ids)])
        self.cat_rule.domain = "[('function', '=', 'Engineer')]"
        self.assertIn('Engineer', self.field_domain('res.partner', 'parent_id'))

    def test_users_field_filter_by_group_and_category(self):
        self.make_filter(self.user_field, group_ids=[Command.set(self.sales_group.ids)])
        domain = safe_eval(self.field_domain('res.partner', 'user_id'))
        users = self.env['res.users'].search(domain)
        self.assertEqual(users, self.seller)
        self.seller.partner_id.contact_category_ids = [Command.set(self.cat_installer.ids)]
        self.env['contact.field.filter'].search([]).write({
            'group_ids': [Command.clear()], 'category_ids': [Command.set(self.cat_installer.ids)]})
        domain = safe_eval(self.field_domain('res.partner', 'user_id'))
        self.assertEqual(self.env['res.users'].search(domain), self.seller)

    def test_enforce(self):
        self.make_filter(self.parent_field, category_ids=[Command.set(self.cat_customer.ids)], enforce=True)
        admin_env = self.env(user=self.env.ref('base.user_admin'), su=False)
        partner = admin_env['res.partner'].create({'name': 'P', 'parent_id': self.customer.id})
        with self.assertRaises(ValidationError):
            partner.write({'parent_id': self.installer.id})
        with self.assertRaises(ValidationError):
            admin_env['res.partner'].create({'name': 'Q', 'parent_id': self.installer.id})
        # superuser flows (website, portal, mail gateway...) are not blocked
        partner.sudo().write({'parent_id': self.installer.id})

    def test_not_enforced_by_default(self):
        self.make_filter(self.parent_field, category_ids=[Command.set(self.cat_customer.ids)])
        admin_env = self.env(user=self.env.ref('base.user_admin'), su=False)
        admin_env['res.partner'].create({'name': 'Q', 'parent_id': self.installer.id})

    def test_filter_validation(self):
        with self.assertRaises(ValidationError):
            self.make_filter(self.parent_field)
        name_field = self.env['ir.model.fields']._get('res.partner', 'name')
        with self.assertRaises(ValidationError):
            self.make_filter(name_field, category_ids=[Command.set(self.cat_customer.ids)])
