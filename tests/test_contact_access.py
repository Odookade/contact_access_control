from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import ContactAccessCommon


@tagged('post_install', '-at_install', 'contact_access')
class TestContactAccess(ContactAccessCommon):

    def all_test_partners(self):
        return (self.customer | self.customer_child | self.installer | self.free
                | self.technician | self.technician_child | self.b_partner)

    # ------------------------------------------------------------------
    # Default: nothing granted
    # ------------------------------------------------------------------
    def test_no_grant_sees_nothing_but_whitelist(self):
        self.assertFalse(self.visible(self.user, self.all_test_partners()))
        Partner = self.env['res.partner'].with_user(self.user)
        with self.assertRaises(AccessError):
            self.customer.with_user(self.user).read(['name'])
        self.assertFalse(Partner.name_search('Cust'))
        self.assertFalse(Partner.search_read([('name', 'ilike', 'Agent')], ['name']))
        # whitelist: internal users' partners, own partner, company partners
        whitelist = self.env.ref('base.partner_admin') | self.user.partner_id | self.company_a.partner_id
        self.assertEqual(self.visible(self.user, whitelist), whitelist)
        # res.users inherits partner rules (_inherits): internal users stay visible
        self.assertIn(self.env.ref('base.user_admin'), self.env['res.users'].with_user(self.user).search([]))
        # own partner remains editable (preferences)
        self.user.partner_id.with_user(self.user).write({'phone': '123'})
        with self.assertRaises(AccessError):
            self.env.ref('base.partner_admin').with_user(self.user).write({'phone': '123'})

    def test_users_without_level_are_unaffected(self):
        self.assertEqual(self.visible(self.plain_user, self.all_test_partners() - self.b_partner),
                         self.all_test_partners() - self.b_partner)

    def test_full_level_sees_everything(self):
        self.assertEqual(self.visible(self.full_user, self.all_test_partners() - self.b_partner),
                         self.all_test_partners() - self.b_partner)
        self.free.with_user(self.full_user).write({'phone': '1'})
        self.free.with_user(self.full_user).action_archive()

    # ------------------------------------------------------------------
    # Grants
    # ------------------------------------------------------------------
    def test_user_line_grants_read_with_children(self):
        self.grant(self.cat_customer, users=self.user)
        self.assertEqual(self.visible(self.user, self.all_test_partners()), self.customer | self.customer_child)
        self.assertFalse(self.visible(self.user2, self.all_test_partners()))
        with self.assertRaises(AccessError):
            self.customer.with_user(self.user).write({'phone': '1'})
        with self.assertRaises(AccessError):
            self.customer_child.with_user(self.user).unlink()

    def test_group_line(self):
        self.grant(self.cat_installer, groups=self.team_group)
        self.assertFalse(self.visible(self.user, self.installer))
        self.user.write({'group_ids': [Command.link(self.team_group.id)]})
        self.assertEqual(self.visible(self.user, self.all_test_partners()), self.installer)

    def test_group_membership_from_group_side(self):
        """Adding / removing the user from the group form must refresh rule domains."""
        self.grant(self.cat_installer, groups=self.team_group)
        self.assertFalse(self.visible(self.user, self.installer))
        self.team_group.write({'user_ids': [Command.link(self.user.id)]})
        self.assertEqual(self.visible(self.user, self.installer), self.installer)
        self.team_group.write({'user_ids': [Command.unlink(self.user.id)]})
        self.assertFalse(self.visible(self.user, self.installer))

    def test_access_change_is_effective_immediately(self):
        line = self.grant(self.cat_customer, users=self.user)
        self.assertTrue(self.visible(self.user, self.customer))
        line.write({'user_ids': [Command.clear()], 'group_ids': [Command.link(self.team_group.id)]})
        self.assertFalse(self.visible(self.user, self.customer))
        self.cat_customer.action_archive()
        self.user.write({'group_ids': [Command.link(self.team_group.id)]})
        self.assertFalse(self.visible(self.user, self.customer))

    def test_write_create_unlink_permissions(self):
        self.grant(self.cat_customer, users=self.user, perm_write=True)
        self.customer.with_user(self.user).write({'phone': '42'})
        self.assertEqual(self.customer.phone, '42')
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.user).create({
                'name': 'X', 'contact_category_ids': [Command.set(self.cat_customer.ids)]})
        with self.assertRaises(AccessError):
            self.customer_child.with_user(self.user).unlink()

        self.grant(self.cat_customer, users=self.user, perm_create=True, perm_unlink=True)
        new = self.env['res.partner'].with_user(self.user).create({'name': 'New Cust'})
        self.assertEqual(new.contact_category_ids, self.cat_customer, "default creatable category assigned")
        new.unlink()
        self.assertFalse(new.exists())

    def test_create_requires_edit_right(self):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self.env['contact.category.access'].create({
                'category_id': self.cat_customer.id, 'user_ids': [Command.set(self.user.ids)],
                'perm_create': True})
            self.env.flush_all()

    def test_create_without_any_creatable_category_fails(self):
        self.grant(self.cat_customer, users=self.user)
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.user).create({'name': 'Nope'})

    def test_create_in_forbidden_category(self):
        self.grant(self.cat_customer, users=self.user, perm_create=True)
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.user).create({
                'name': 'X', 'contact_category_ids': [Command.set((self.cat_customer | self.cat_installer).ids)]})

    def test_create_uses_context_default(self):
        self.grant(self.cat_customer | self.cat_installer, users=self.user, perm_create=True)
        partner = self.env['res.partner'].with_user(self.user).with_context(
            default_contact_category_ids=self.cat_installer.ids).create({'name': 'Ctx'})
        self.assertEqual(partner.contact_category_ids, self.cat_installer)

    def test_child_inherits_categories(self):
        self.grant(self.cat_customer, users=self.user, perm_create=True)
        child = self.env['res.partner'].with_user(self.user).create({
            'name': 'Invoice Addr', 'type': 'invoice', 'parent_id': self.customer.id})
        self.assertEqual(child.contact_category_ids, self.cat_customer)
        # cannot attach a child to an invisible parent
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.user).create({'name': 'Y', 'parent_id': self.installer.id})

    def test_child_creation_updates_parent_address(self):
        """Odoo 19 pushes a new contact's address up to its parent as the current user."""
        self.grant(self.cat_customer, users=self.user, perm_create=True)
        self.env['res.partner'].with_user(self.user).create({
            'name': 'Contact With Address', 'type': 'contact', 'parent_id': self.customer.id,
            'city': 'Tabriz'})
        self.assertEqual(self.customer.city, 'Tabriz')

    def test_child_of_uncategorized_parent(self):
        """Odoo 19 only syncs set commercial values: the child keeps its own categories."""
        self.grant(self.cat_installer, users=self.user, perm_create=True)
        self.grant(self.cat_rule, users=self.user)
        child = self.env['res.partner'].with_user(self.user).create({
            'name': 'Tech Contact', 'parent_id': self.technician.id})
        self.assertEqual(child.contact_category_ids, self.cat_installer)

    def test_commercial_sync_of_categories(self):
        self.customer.contact_category_ids = [Command.link(self.cat_installer.id)]
        self.assertEqual(self.customer_child.contact_category_ids, self.cat_customer | self.cat_installer)

    def test_category_change_guard(self):
        self.grant(self.cat_customer, users=self.user, perm_write=True)
        with self.assertRaises(AccessError):
            self.customer.with_user(self.user).write({
                'contact_category_ids': [Command.link(self.cat_installer.id)]})
        self.grant(self.cat_installer, users=self.user, perm_write=True)
        self.customer.with_user(self.user).write({'contact_category_ids': [Command.link(self.cat_installer.id)]})
        self.assertIn(self.cat_installer, self.customer.contact_category_ids)

    def test_parent_change_cannot_move_contact_between_categories(self):
        self.grant(self.cat_installer, users=self.user, perm_write=True)
        self.grant(self.cat_customer, users=self.user)  # read only
        with self.assertRaises(AccessError):
            self.installer.with_user(self.user).write({'parent_id': self.customer.id})
        self.assertFalse(self.installer.parent_id)
        self.grant(self.cat_customer, users=self.user, perm_write=True)
        self.installer.with_user(self.user).write({'parent_id': self.customer.id})
        self.assertEqual(self.installer.contact_category_ids, self.cat_customer)

    def test_archive_permission(self):
        self.grant(self.cat_customer, users=self.user, perm_write=True)
        with self.assertRaises(AccessError):
            self.customer.with_user(self.user).action_archive()
        self.grant(self.cat_customer, users=self.user, perm_archive=True, perm_write=True)
        self.customer.with_user(self.user).action_archive()
        self.assertFalse(self.customer.active)
        self.customer.with_user(self.user).action_unarchive()
        self.assertTrue(self.customer.active)

    # ------------------------------------------------------------------
    # Rule-based categories
    # ------------------------------------------------------------------
    def test_rule_category(self):
        self.grant(self.cat_rule, users=self.user)
        self.assertEqual(self.visible(self.user, self.all_test_partners()),
                         self.technician | self.technician_child)
        self.free.function = 'Technician'
        self.assertIn(self.free, self.visible(self.user, self.all_test_partners()))
        self.assertIn(self.cat_rule, self.technician_child.contact_category_match_ids)
        self.assertEqual(
            self.env['res.partner'].search([('id', 'in', self.all_test_partners().ids),
                                            ('contact_category_match_ids', 'in', self.cat_rule.ids)]),
            self.technician | self.technician_child | self.free)
        self.assertEqual(
            self.env['res.partner'].search([('id', 'in', self.all_test_partners().ids),
                                            ('contact_category_match_ids', 'ilike', 'Rule Tech')]),
            self.technician | self.technician_child | self.free)

    def test_rule_category_validation(self):
        with self.assertRaises(ValidationError):
            self.Category.create({'name': 'Everything', 'assignment': 'rule', 'domain': '[]'})
        with self.assertRaises(ValidationError):
            self.Category.create({'name': 'Bad', 'assignment': 'rule', 'domain': "[('nope', '=', 1)]"})
        with self.assertRaises(ValidationError):
            self.Category.create({'name': 'Ctx', 'assignment': 'rule', 'domain': "[('id', '=', uid)]"})
        with self.assertRaises(ValidationError):
            self.cat_customer.assignment = 'rule'

    # ------------------------------------------------------------------
    # Multi-company
    # ------------------------------------------------------------------
    def test_company_specific_category(self):
        self.grant(self.cat_company_b, users=self.user)
        self.assertFalse(self.visible(self.user, self.b_partner, companies=self.company_a))
        self.assertEqual(self.visible(self.user, self.b_partner, companies=self.company_b), self.b_partner)
        self.assertEqual(self.visible(self.user, self.b_partner, companies=self.company_a | self.company_b),
                         self.b_partner)

    def test_global_company_rule_still_applies(self):
        self.customer.company_id = self.company_b
        self.grant(self.cat_customer, users=self.user2)  # user2 only belongs to company A
        self.assertNotIn(self.customer, self.visible(self.user2, self.customer))

    # ------------------------------------------------------------------
    # Leak paths
    # ------------------------------------------------------------------
    def test_other_read_paths(self):
        self.grant(self.cat_customer, users=self.user)
        Partner = self.env['res.partner'].with_user(self.user)
        names = [n for _i, n in Partner.name_search('', limit=1000)]
        self.assertIn('Cust Corp', names)
        self.assertNotIn('Free Agent', names)
        groups = Partner.formatted_read_group([('id', 'in', self.all_test_partners().ids)], [], ['__count'])
        self.assertEqual(groups[0]['__count'], 2)
        # export needs base.group_allow_export, and only exports accessible rows
        with self.assertRaises(UserError):
            Partner.search([]).export_data(['name'])
        self.user.write({'group_ids': [Command.link(self.env.ref('base.group_allow_export').id)]})
        exported = Partner.search([('id', 'in', self.all_test_partners().ids)]).export_data(['name'])['datas']
        self.assertEqual(sorted(r[0] for r in exported), ['Cust Corp', 'Cust Person'])
        # @mention suggestions (mail) go through _search, so rules apply
        self.assertEqual(self.env['res.partner'].sudo()._search_mention_suggestions(
            Partner._get_mention_suggestions_domain('Free Agent'), 8), self.free)
        self.assertFalse(Partner._search_mention_suggestions(
            Partner._get_mention_suggestions_domain('Free Agent'), 8))
        self.assertIn(self.customer, Partner._search_mention_suggestions(
            Partner._get_mention_suggestions_domain('Cust Corp'), 8))
        # following a hidden many2one shows its name but not the record
        with self.assertRaises(AccessError):
            self.free.with_user(self.user).email  # noqa: B018

    def test_chatter_message_from_hidden_author(self):
        self.grant(self.cat_customer, users=self.user)
        message = self.customer.message_post(body='Hello', author_id=self.free.id,
                                             message_type='comment', subtype_xmlid='mail.mt_comment')
        values = message.with_user(self.user).read(['author_id', 'body'])[0]
        self.assertEqual(values['author_id'], (self.free.id, 'Free Agent'))

    def test_mail_find_or_create_uses_default_category(self):
        """Known limitation: an existing but hidden partner is not found, a new one is
        created in the user's default creatable category."""
        self.grant(self.cat_customer, users=self.user, perm_create=True)
        self.free.email = 'free@example.com'
        partner = self.env['res.partner'].with_user(self.user).find_or_create('free@example.com')
        self.assertNotEqual(partner, self.free)
        self.assertEqual(partner.contact_category_ids, self.cat_customer)

    def test_portal_user_unaffected(self):
        portal = self.env['res.users'].create({
            'name': 'Portal Joe', 'login': 'portaljoe',
            'group_ids': [Command.set(self.env.ref('base.group_portal').ids)]})
        portal.partner_id.parent_id = self.customer
        own = self.env['res.partner'].with_user(portal).search([('id', 'in', (self.customer | self.free).ids)])
        self.assertEqual(own, self.customer)
