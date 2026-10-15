from odoo import models

from .contact_field_filter import FILTERABLE_COMODELS


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def _postprocess_tag_field(self, node, name_manager, node_info):
        """AND configured contact filters into the domain of matching field nodes.

        Runs during view post-processing for the actual model of each node (including
        embedded x2many sub-views), before the standard processing so the resulting
        domain is validated and its dependencies are collected as usual. The resulting
        arch is cached for all users in the ``templates`` cache, which the filter and
        category models clear when they change.
        """
        name = node.get('name')
        if name and node_info.get('view_type') != 'search' and self.pool.ready:
            model = name_manager.model
            field = model._fields.get(name)
            if field and field.type in ('many2one', 'many2many') and field.comodel_name in FILTERABLE_COMODELS:
                Filter = self.env['contact.field.filter']
                policy = Filter._get_filter_domain(model._name, name)
                if policy is not None:
                    original = node.get('domain') or field._description_domain(self.env)
                    node.set('domain', Filter._combine_with_domain(policy, original))
        return super()._postprocess_tag_field(node, name_manager, node_info)
