from odoo import _, models
from odoo.exceptions import ValidationError


class Base(models.AbstractModel):
    _inherit = 'base'

    def _validate_fields(self, field_names, excluded_names=()):
        """Server-side enforcement of contact field filters flagged ``enforce``.

        Cheap exit for every model without an enforced filter (one ormcache lookup).
        Not applied to superuser operations (portal/website/mail flows run as sudo)
        nor while the registry is loading (module install / upgrade).
        """
        field_names = set(field_names)
        super()._validate_fields(field_names, excluded_names)
        if not self or self.env.su or not self.pool.ready:
            return
        filters = self.env['contact.field.filter']._get_enforced_filters(self._name)
        if not filters:
            return
        for fname in field_names & filters.keys() - set(excluded_names):
            field = self._fields[fname]
            values = self.mapped(fname)
            if not values:
                continue
            Comodel = self.env[field.comodel_name].sudo().with_context(active_test=False)
            valid = Comodel.search([('id', 'in', values.ids)] + filters[fname])
            invalid = values.sudo() - valid
            if invalid:
                raise ValidationError(_(
                    "%(names)s cannot be selected in field \"%(field)s\".",
                    names=', '.join(invalid.mapped('display_name')),
                    field=field._description_string(self.env),
                ))
