{
    'name': 'Contact Access Control',
    'version': '20.0.1.0.0',
    'summary': 'Category-based contact security and centralized contact selection filters',
    'description': """
Contact Access Control
======================

* Admin-defined contact categories (manual or rule-based), a contact can belong to many.
* Per-category access lines (users / groups) with read, write, create, delete and archive rights,
  enforced server-side through ir.access restrictions (ORM, RPC, name_search, export, mentions...).
* Centralized filters for res.partner / res.users selection fields of any model,
  injected into views, optionally enforced on save.
* Single and multi-company support.
* Installing the module changes nothing until users are put in the
  "Restricted" access level.
""",
    'author': 'Erfan Meraati | Odookade',
    'website': 'https://www.Odookade.ir',
    'category': 'Sales/Contacts',
    'license': 'LGPL-3',
    'depends': ['contacts'],
    'data': [
        'security/contact_access_security.xml',
        'security/ir.access.csv',
        'views/contact_category_views.xml',
        'views/contact_field_filter_views.xml',
        'views/res_partner_views.xml',
        'views/contact_access_menus.xml',
    ],
    'installable': True,
    'application': False,
}
