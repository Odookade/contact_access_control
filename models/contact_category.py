from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval


class ContactCategory(models.Model):
    """Admin-defined classification of contacts used by access lines and field filters.

    A category is either:

    * ``manual``: membership is stored in ``res.partner.contact_category_ids``;
    * ``rule``: membership is a static domain evaluated at search time. Nothing is
      stored, so it stays correct even when the underlying data is changed by raw SQL
      (e.g. ``customer_rank`` / ``supplier_rank`` in ``account``).
    """
    _name = 'contact.category'
    _description = 'Contact Access Category'
    _order = 'sequence, name, id'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()
    description = fields.Text(translate=True)
    company_id = fields.Many2one(
        'res.company', index=True,
        help="Leave empty to share the category between all companies. When set, its access "
             "lines only apply while that company is active in the company switcher.")
    assignment = fields.Selection(
        [('manual', 'Manual'), ('rule', 'Rule-based')],
        required=True, default='manual',
        help="Manual: contacts are added to the category explicitly.\n"
             "Rule-based: every contact matching the domain belongs to the category.")
    domain = fields.Char(
        string='Membership Rule', default='[]',
        help="Static domain on contacts. Only used for rule-based categories.")
    access_ids = fields.One2many('contact.category.access', 'category_id', string='Access', copy=True)
    partner_count = fields.Integer(compute='_compute_partner_count', string='Contacts')

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------
    def _get_rule_domain(self):
        self.ensure_one()
        return Domain(safe_eval(self.domain or '[]'))

    def _get_partner_domain(self):
        """Domain on res.partner matching members of any category in ``self``.

        Children (contacts, addresses) belong to the categories of their commercial
        entity: manual categories are synced to them (``_commercial_fields``), rule-based
        ones also match through ``commercial_partner_id``.
        """
        domains = []
        manual = self.filtered(lambda c: c.assignment == 'manual')
        if manual:
            domains.append([('contact_category_ids', 'in', manual.ids)])
        for category in self - manual:
            rule_domain = category._get_rule_domain()
            domains.append(rule_domain)
            domains.append(Domain('commercial_partner_id', 'any', list(rule_domain)))
        return Domain.OR(domains)

    @api.constrains('assignment', 'domain')
    def _check_domain(self):
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        sample = Partner.search([], limit=1)
        for category in self.filtered(lambda c: c.assignment == 'rule'):
            try:
                domain = category._get_rule_domain()
            except Exception as e:  # noqa: BLE001 - surface any evaluation error to the admin
                raise ValidationError(_("Invalid membership rule for category %(name)s: %(error)s",
                                        name=category.name, error=e)) from e
            if domain.is_true():
                raise ValidationError(_(
                    "The membership rule of category %s is empty: it would match every contact.",
                    category.name))
            if any(isinstance(leaf, (list, tuple)) and str(leaf[0]).split('.')[0] in
                   ('contact_category_ids', 'contact_category_match_ids') for leaf in list(domain)):
                raise ValidationError(_("A membership rule cannot refer to access categories."))
            try:
                # validates both SQL search and the in-memory evaluation used by access checks
                with self.env.cr.savepoint():
                    Partner.search_count(domain, limit=1)
                sample.filtered_domain(domain)
            except Exception as e:  # noqa: BLE001
                raise ValidationError(_("Invalid membership rule for category %(name)s: %(error)s",
                                        name=category.name, error=e)) from e

    # ------------------------------------------------------------------
    # Compute / actions
    # ------------------------------------------------------------------
    def _compute_partner_count(self):
        Partner = self.env['res.partner']
        for category in self:
            category.partner_count = Partner.search_count(category._get_partner_domain()) if category.id else 0

    def action_view_partners(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('contacts.action_contacts')
        action.update({
            'domain': self._get_partner_domain(),
            'context': {'default_contact_category_ids': [self.id]} if self.assignment == 'manual' else {},
            'display_name': self.name,
        })
        return action

    # ------------------------------------------------------------------
    # Cache invalidation (Odoo 20): access domains and record access cache through
    # ir.access._clear_caches(), and views with injected filters (templates cache)
    # ------------------------------------------------------------------
    def _invalidate_contact_access_caches(self):
        self.env['ir.access']._clear_caches()
        self.env.transaction.invalidate_ormcache('templates')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._invalidate_contact_access_caches()
        return records

    def write(self, vals):
        if 'assignment' in vals and self.env['res.partner'].sudo().search_count(
                [('contact_category_ids', 'in', self.ids)], limit=1):
            if vals['assignment'] == 'rule':
                raise ValidationError(_(
                    "Remove the contacts manually assigned to this category before turning it into a rule-based one."))
        res = super().write(vals)
        self._invalidate_contact_access_caches()
        return res

    def unlink(self):
        res = super().unlink()
        self._invalidate_contact_access_caches()
        return res
