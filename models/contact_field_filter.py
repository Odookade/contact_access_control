from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError
from odoo.fields import Domain

FILTERABLE_COMODELS = ('res.partner', 'res.users')


class ContactFieldFilter(models.Model):
    """Restricts which contacts / users can be selected in a relational field.

    The filter is AND-ed with the field's own domain (view attribute or field
    definition) when views are post-processed, so the selection dropdown, the
    "Search More" dialog and quick search all honour it. With ``enforce``, the
    value is also validated server-side on create/write (non-sudo only).

    This is an operational filter, identical for every user. Confidentiality is
    handled by the access categories (record rules), not here.
    """
    _name = 'contact.field.filter'
    _description = 'Contact Selection Field Filter'
    _order = 'model_id, field_id'
    _rec_name = 'field_id'

    active = fields.Boolean(default=True)
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', index=True)
    model = fields.Char(related='model_id.model', store=True, string='Model Name')
    field_id = fields.Many2one(
        'ir.model.fields', required=True, ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', 'in', ('many2one', 'many2many')),"
               " ('relation', 'in', ('res.partner', 'res.users'))]")
    comodel = fields.Char(related='field_id.relation', string='Target')
    category_ids = fields.Many2many(
        'contact.category', 'contact_field_filter_category_rel', 'filter_id', 'category_id',
        string='Allowed Categories')
    group_ids = fields.Many2many(
        'res.groups', 'contact_field_filter_group_rel', 'filter_id', 'group_id',
        string='Allowed User Groups',
        help="Also allow users (or partners of users) belonging to these groups, "
             "e.g. Sales / User for a salesperson field.")
    enforce = fields.Boolean(
        'Enforce on Save',
        help="Also refuse, server-side, values that do not match the filter when a record is "
             "created or modified by a user (operations run as superuser are not checked).")
    note = fields.Text()

    _field_uniq = models.Constraint(
        'unique(field_id)',
        "Only one filter can be defined per field.",
    )

    @api.constrains('field_id', 'model_id', 'category_ids', 'group_ids')
    def _check_field(self):
        for flt in self:
            if flt.field_id.model_id != flt.model_id:
                raise ValidationError(_("The field must belong to the selected model."))
            if flt.field_id.ttype not in ('many2one', 'many2many') or \
                    flt.field_id.relation not in FILTERABLE_COMODELS:
                raise ValidationError(_("Only many2one / many2many fields to contacts or users can be filtered."))
            if not flt.category_ids and not flt.group_ids:
                raise ValidationError(_("Select at least one category or user group."))

    # ------------------------------------------------------------------
    def _compute_filter_domain(self):
        """Static domain (no user/context dependent values: views are cached for all users)."""
        self.ensure_one()
        categories = self.category_ids.filtered('active')
        partner_domain = categories._get_partner_domain() if categories else None
        group_ids = self.group_ids.ids
        domains = []
        if self.field_id.relation == 'res.partner':
            if partner_domain:
                domains.append(partner_domain)
            if group_ids:
                domains.append(Domain('user_ids.all_group_ids', 'in', group_ids))
        else:
            if partner_domain:
                domains.append(Domain('partner_id', 'any', list(partner_domain)))
            if group_ids:
                domains.append(Domain('all_group_ids', 'in', group_ids))
        # plain list: it is stored in a cache and rendered with repr() into view archs
        return list(Domain.OR(domains))

    @api.model
    @tools.ormcache()
    def _get_filter_map(self):
        """{(model, field): (domain, enforce)}; cleared on any filter/category change."""
        result = {}
        for flt in self.sudo().search([]):
            result[(flt.model, flt.field_id.name)] = (tuple(flt._compute_filter_domain()), flt.enforce)
        return result

    @api.model
    def _get_filter_domain(self, model_name, field_name):
        entry = self._get_filter_map().get((model_name, field_name))
        return list(entry[0]) if entry else None

    @api.model
    def _get_enforced_filters(self, model_name):
        return {
            fname: list(domain)
            for (model, fname), (domain, enforce) in self._get_filter_map().items()
            if model == model_name and enforce
        }

    @api.model
    def _combine_with_domain(self, policy, original):
        """AND ``policy`` (list) with a field domain given as a list or a client-side expression."""
        if not original:
            return repr(policy)
        if isinstance(original, (list, tuple, Domain)):
            return repr(list(Domain(policy) & Domain(list(original))))
        # Same technique as fields._Relational._description_domain (check_company):
        # concatenation of a normalized domain with another domain is an implicit AND.
        return f"{policy!r} + ({original})"

    # ------------------------------------------------------------------
    def _invalidate_caches(self):
        self.env.registry.clear_cache()
        self.env.registry.clear_cache('templates')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._invalidate_caches()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._invalidate_caches()
        return res

    def unlink(self):
        res = super().unlink()
        self._invalidate_caches()
        return res
