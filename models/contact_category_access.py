from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

# operation -> permission field granting it ("read" is granted by every line)
OPERATION_FIELDS = {
    'read': None,
    'write': 'perm_write',
    'create': 'perm_create',
    'unlink': 'perm_unlink',
    'archive': 'perm_archive',
}


class ContactCategoryAccess(models.Model):
    """Grants a set of users / groups rights on the contacts of one category.

    Every line grants read access; other rights are opt-in. Lines only have an
    effect on users of the "Contacts Access: Restricted" level: users with the
    full level, or without any contact access level, keep the standard Odoo
    behaviour.
    """
    _name = 'contact.category.access'
    _description = 'Contact Category Access'
    _order = 'category_id, id'

    category_id = fields.Many2one('contact.category', required=True, ondelete='cascade', index=True)
    user_ids = fields.Many2many(
        'res.users', 'contact_category_access_user_rel', 'access_id', 'user_id',
        string='Users', domain=[('share', '=', False)])
    group_ids = fields.Many2many(
        'res.groups', 'contact_category_access_group_rel', 'access_id', 'group_id',
        string='Groups', domain=[('share', '=', False)])
    perm_write = fields.Boolean('Edit')
    perm_create = fields.Boolean('Create')
    perm_unlink = fields.Boolean('Delete')
    perm_archive = fields.Boolean('Archive')

    # Creating a contact can write on contacts as the current user: in Odoo 19 a new
    # child contact pushes its address / VAT up to its parent (base res_partner
    # _fields_sync and _handle_first_contact_creation), and archiving is a write.
    # Create and Archive are therefore meaningless without the Edit right.
    # NULL-safe: Odoo stores False booleans as NULL
    _create_needs_write = models.Constraint(
        'CHECK(perm_create IS NOT TRUE OR perm_write IS TRUE)',
        "The Create right requires the Edit right.",
    )
    _archive_needs_write = models.Constraint(
        'CHECK(perm_archive IS NOT TRUE OR perm_write IS TRUE)',
        "The Archive right requires the Edit right.",
    )

    @api.onchange('perm_create', 'perm_archive')
    def _onchange_perm_implies_write(self):
        for line in self:
            if line.perm_create or line.perm_archive:
                line.perm_write = True

    @api.onchange('perm_write')
    def _onchange_perm_write(self):
        for line in self.filtered(lambda line: not line.perm_write):
            line.perm_create = line.perm_archive = False

    @api.constrains('user_ids', 'group_ids')
    def _check_target(self):
        for line in self:
            if not line.user_ids and not line.group_ids:
                raise ValidationError(_("Each access line of category %s needs at least one user or group.",
                                        line.category_id.name))

    # ------------------------------------------------------------------
    # Resolution (always sudo: called from record-rule evaluation)
    # ------------------------------------------------------------------
    @api.model
    def _get_granted_categories(self, user, operation, company_ids):
        perm_field = OPERATION_FIELDS[operation]
        user = user.sudo()
        domain = [
            ('category_id.active', '=', True),
            '|', ('category_id.company_id', '=', False), ('category_id.company_id', 'in', company_ids),
            '|', ('user_ids', 'in', user.ids), ('group_ids', 'in', user.all_group_ids.ids),
        ]
        if perm_field:
            domain.append((perm_field, '=', True))
        return self.sudo().with_context(active_test=False).search(domain).category_id

    @api.model
    def _get_whitelist_domain(self, user, operation):
        """Contacts a restricted user always needs, whatever the categories.

        * read: partners of internal users (``partner_share = False``, same exception as
          ``base.res_partner_rule``) because ``res.users`` inherits ``res.partner`` record
          rules through ``_inherits``; hiding them would break salesperson fields,
          activities, chatter...; the companies' partners; the user's own commercial entity.
        * write: the user's own partner (preferences are stored on it).
        """
        user = user.sudo()
        if operation == 'read':
            return Domain.OR([
                Domain('partner_share', '=', False),
                Domain('id', 'in', user.company_ids.partner_id.ids),
                Domain('commercial_partner_id', '=', user.commercial_partner_id.id),
            ])
        if operation == 'write':
            return Domain('id', '=', user.partner_id.id)
        return Domain.FALSE

    @api.model
    def _get_partner_access_domain(self, user, operation, company_ids):
        categories = self._get_granted_categories(user, operation, company_ids)
        domains = [self._get_whitelist_domain(user, operation)]
        if categories:
            domains.append(categories._get_partner_domain())
        return Domain.OR(domains)

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res
