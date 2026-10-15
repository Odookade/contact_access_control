from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command, Domain


def _apply_x2many_commands(ids, commands):
    """Return the set of ids obtained by applying x2many ``commands`` on ``ids``."""
    result = set(ids)
    if not commands:
        return result
    if all(isinstance(cmd, int) for cmd in commands):
        return set(commands)
    for cmd in commands:
        if isinstance(cmd, int):
            result.add(cmd)
        elif cmd[0] == Command.SET:
            result = set(cmd[2] or [])
        elif cmd[0] == Command.LINK:
            result.add(cmd[1])
        elif cmd[0] in (Command.UNLINK, Command.DELETE):
            result.discard(cmd[1])
        elif cmd[0] == Command.CLEAR:
            result = set()
        elif cmd[0] == Command.CREATE:
            raise UserError(_("Access categories cannot be created from a contact."))
    return result


class ResPartner(models.Model):
    _inherit = 'res.partner'

    contact_category_ids = fields.Many2many(
        'contact.category', 'res_partner_contact_category_rel', 'partner_id', 'category_id',
        string='Access Categories', domain=[('assignment', '=', 'manual')],
        help="Manual access categories. Child contacts and addresses inherit the categories "
             "of their commercial entity.")
    contact_category_match_ids = fields.Many2many(
        'contact.category', string='All Access Categories',
        compute='_compute_contact_category_match_ids', search='_search_contact_category_match_ids',
        help="Manual categories plus rule-based categories this contact matches.")

    # ------------------------------------------------------------------
    # Access scope (Odoo 20)
    # ------------------------------------------------------------------
    def _access_domain(self, operation):
        """AND the category scope of restricted users into the security domain.

        Odoo 20 OR-s group permissions and base / business apps grant unconditional
        permissions on res.partner, so the scope must be a restriction. It is applied
        here, like core does for cross-module conditions (mail.mail, quotation documents),
        rather than as a global ir.access record: a global record would reference values
        that only exist while this module's code is loaded, and break contact access for
        every user otherwise (e.g. during a partial registry load).

        ``res.users`` gets the same scope through ``_inherits`` (``_check_inherits_access``).
        Both parts are cached per user and active companies; ``ir.access._clear_caches()``
        invalidates them.
        """
        domain = super()._access_domain(operation)
        if domain.is_false():
            return domain
        scope = self.env['contact.category.access']._get_contact_access_domains()[operation]
        return domain if scope.is_true() else domain & scope

    @api.model
    def _commercial_fields(self):
        # Downstream only (commercial entity -> descendants). Deliberately not added to
        # _synced_commercial_fields(), which in Odoo 19 also propagates child edits upstream.
        return super()._commercial_fields() + ['contact_category_ids']

    @api.depends('contact_category_ids')
    def _compute_contact_category_match_ids(self):
        rule_categories = self.env['contact.category'].sudo().search([('assignment', '=', 'rule')])
        real = self.filtered('id')
        matches = {}
        for category in rule_categories:
            matched = real.sudo().with_context(active_test=False).search(
                Domain('id', 'in', real.ids) & category._get_partner_domain())
            for partner_id in matched.ids:
                matches.setdefault(partner_id, []).append(category.id)
        for partner in self:
            partner.contact_category_match_ids = partner.contact_category_ids | \
                self.env['contact.category'].browse(matches.get(partner.id, []))

    def _search_contact_category_match_ids(self, operator, value):
        Category = self.env['contact.category'].sudo()
        if operator in ('=', '!=') and value is False:
            # "has no category at all" is not meaningful for rule-based categories
            raise UserError(_("Unsupported search on access categories."))
        if operator in ('in', 'not in', '=', '!='):
            # Odoo 19 passes 'in' values as an OrderedSet
            ids = [value] if isinstance(value, (int, str)) else list(value)
            categories = Category.browse([i for i in ids if isinstance(i, int)])
            if any(isinstance(i, str) for i in ids):
                categories |= Category.search([('name', 'in', [i for i in ids if isinstance(i, str)])])
        elif operator in ('any', 'not any', 'any!', 'not any!'):
            # Odoo 19 rewrites name searches on relational fields into
            # ('field', 'any', <domain on contact.category>)
            categories = Category.with_context(active_test=False).search(Domain(value))
            operator = 'not in' if operator.startswith('not') else 'in'
        elif operator in ('ilike', 'not ilike', 'like', '=like', '=ilike'):
            positive = operator.replace('not ', '')
            categories = Category.search([('name', positive, value)])
            operator = 'not in' if operator.startswith('not') else 'in'
        else:
            raise UserError(_("Unsupported operator %s on access categories.", operator))
        domain = categories.exists()._get_partner_domain()
        return ~domain if operator in ('not in', '!=') else domain

    # ------------------------------------------------------------------
    # Write guards for restricted users. Row-level permissions themselves are
    # enforced by the ir.access restrictions; these only cover what a domain cannot express.
    # ------------------------------------------------------------------
    def _contact_access_is_restricted(self):
        user = self.env.user
        return (
            not self.env.su
            and user.has_group('contact_access_control.group_contact_access_restricted')
            and not user.has_group('contact_access_control.group_contact_access_full')
        )

    def _contact_access_categories(self, operation):
        return self.env['contact.category.access']._get_granted_categories(
            self.env.user, operation, self.env.companies.ids,
        ).filtered(lambda c: c.assignment == 'manual')

    @api.model_create_multi
    def create(self, vals_list):
        if self._contact_access_is_restricted():
            self._contact_access_prepare_create(vals_list)
        return super().create(vals_list)

    def _contact_access_prepare_create(self, vals_list):
        creatable = self._contact_access_categories('create')
        defaults = None
        for vals in vals_list:
            parent_id = vals.get('parent_id')
            if parent_id and not vals.get('is_company'):
                # child contacts/addresses inherit the categories of their commercial entity
                # (synced by sudo after the create rule check otherwise). Odoo 19 only syncs
                # set values: an uncategorized parent leaves the child's own categories.
                parent = self.browse(parent_id)
                parent.check_access('read')
                parent_categories = parent.sudo().commercial_partner_id.contact_category_ids
                if parent_categories:
                    vals['contact_category_ids'] = [Command.set(parent_categories.ids)]
                    continue
            if 'contact_category_ids' not in vals:
                if defaults is None:
                    defaults = self.default_get(['contact_category_ids'])
                if 'contact_category_ids' in defaults:
                    vals['contact_category_ids'] = defaults['contact_category_ids']
            requested = _apply_x2many_commands(set(), vals.get('contact_category_ids'))
            if not requested:
                if creatable:
                    vals['contact_category_ids'] = [Command.set(creatable[:1].ids)]
                continue
            forbidden = requested - set(creatable.ids)
            if forbidden:
                raise AccessError(_(
                    "You are not allowed to create contacts in these access categories: %s",
                    ', '.join(self.env['contact.category'].sudo().browse(forbidden).mapped('name'))))

    def write(self, vals):
        if self and self._contact_access_is_restricted():
            if 'contact_category_ids' in vals:
                self._contact_access_check_category_change(vals['contact_category_ids'])
            if vals.get('parent_id'):
                self._contact_access_check_parent_change(vals['parent_id'])
            if 'active' in vals:
                self._contact_access_check_archive(bool(vals['active']))
        return super().write(vals)

    def _contact_access_check_category_change(self, commands):
        allowed = set(self._contact_access_categories('write').ids)
        for partner in self.sudo():
            old = set(partner.contact_category_ids.ids)
            changed = old ^ _apply_x2many_commands(old, commands)
            if changed - allowed:
                raise AccessError(_(
                    "You are not allowed to add or remove these access categories: %s",
                    ', '.join(self.env['contact.category'].sudo().browse(changed - allowed).mapped('name'))))

    def _contact_access_check_parent_change(self, parent_id):
        """Attaching contacts to a parent makes them inherit its categories (commercial
        sync runs as sudo): only allowed when the resulting change is one the user could
        make explicitly."""
        parent = self.browse(parent_id)
        parent.check_access('read')
        target = set(parent.sudo().commercial_partner_id.contact_category_ids.ids)
        if not target:
            return  # Odoo 19 does not sync empty commercial values: categories are kept
        allowed = set(self._contact_access_categories('write').ids)
        for partner in self.sudo().filtered(lambda p: not p.is_company):
            changed = set(partner.contact_category_ids.ids) ^ target
            if changed - allowed:
                raise AccessError(_(
                    "Attaching %(contact)s to %(parent)s would change its access categories (%(categories)s), "
                    "which you are not allowed to do.",
                    contact=partner.display_name, parent=parent.sudo().display_name,
                    categories=', '.join(self.env['contact.category'].sudo().browse(changed - allowed).mapped('name'))))

    def _contact_access_check_archive(self, active):
        self.check_access('read')
        to_change = self.filtered(lambda p: p.active != active)
        if not to_change:
            return
        domain = self.env['contact.category.access']._get_partner_access_domain(
            self.env.user, 'archive', self.env.companies.ids)
        forbidden = to_change - to_change.sudo().filtered_domain(domain)
        if forbidden:
            raise AccessError(_(
                "You are not allowed to archive or restore these contacts: %s",
                ', '.join(forbidden.sudo().mapped('display_name'))))
