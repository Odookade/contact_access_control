from odoo import api, models


class IrRule(models.Model):
    _inherit = 'ir.rule'

    @api.model
    def _eval_context(self):
        """Expose ``contact_access_domain(operation)`` to record-rule domains.

        Same extension point as ``website`` uses to expose ``website``. The value is
        only computed when a rule actually calls it (the module's res.partner rules);
        ``ir.rule._compute_domain`` caches the result per user, mode and active
        companies, and the cache is cleared whenever categories, access lines or a
        user's groups change.
        """
        context = super()._eval_context()
        user = self.env.user
        company_ids = context['company_ids']
        Access = self.env['contact.category.access']
        context['contact_access_domain'] = (
            lambda operation: Access._get_partner_access_domain(user, operation, company_ids)
        )
        return context
