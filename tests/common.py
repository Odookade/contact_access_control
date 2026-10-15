from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user

RESTRICTED = 'contact_access_control.group_contact_access_restricted'
FULL = 'contact_access_control.group_contact_access_full'


class ContactAccessCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Company B'})

        cls.Category = cls.env['contact.category']
        cls.cat_customer = cls.Category.create({'name': 'Customers', 'sequence': 1})
        cls.cat_installer = cls.Category.create({'name': 'Installers', 'sequence': 2})
        cls.cat_rule = cls.Category.create({
            'name': 'Rule Technicians', 'assignment': 'rule',
            'domain': "[('function', '=', 'Technician')]",
        })
        cls.cat_company_b = cls.Category.create({'name': 'B Only', 'company_id': cls.company_b.id})

        Partner = cls.env['res.partner']
        cls.customer = Partner.create({
            'name': 'Cust Corp', 'is_company': True,
            'contact_category_ids': [Command.set(cls.cat_customer.ids)],
        })
        cls.customer_child = Partner.create({'name': 'Cust Person', 'parent_id': cls.customer.id})
        cls.installer = Partner.create({
            'name': 'Inst Guy', 'contact_category_ids': [Command.set(cls.cat_installer.ids)],
        })
        cls.free = Partner.create({'name': 'Free Agent'})
        cls.technician = Partner.create({'name': 'Tech Co', 'is_company': True, 'function': 'Technician'})
        cls.technician_child = Partner.create({'name': 'Tech Address', 'parent_id': cls.technician.id,
                                               'type': 'delivery'})
        cls.b_partner = Partner.create({
            'name': 'B Partner', 'contact_category_ids': [Command.set(cls.cat_company_b.ids)],
        })

        groups = f'base.group_user,{RESTRICTED}'
        cls.user = new_test_user(cls.env, 'restricted', groups=groups,
                                 company_ids=[Command.set((cls.company_a | cls.company_b).ids)],
                                 company_id=cls.company_a.id)
        cls.user2 = new_test_user(cls.env, 'restricted2', groups=groups)
        cls.full_user = new_test_user(cls.env, 'fulluser', groups=f'base.group_user,{FULL}')
        cls.plain_user = new_test_user(cls.env, 'plainuser', groups='base.group_user')
        cls.team_group = cls.env['res.groups'].create({'name': 'Installer Team'})

    def grant(self, categories, users=None, groups=None, **perms):
        if perms.get('perm_create') or perms.get('perm_archive'):
            perms.setdefault('perm_write', True)
        return self.env['contact.category.access'].create([{
            'category_id': category.id,
            'user_ids': [Command.set(users.ids)] if users else [],
            'group_ids': [Command.set(groups.ids)] if groups else [],
            **perms,
        } for category in categories])

    def visible(self, user, partners, companies=None):
        env_partner = self.env['res.partner'].with_user(user)
        if companies:
            env_partner = env_partner.with_context(allowed_company_ids=companies.ids)
        return env_partner.search([('id', 'in', partners.ids)])
