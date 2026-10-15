# Contact Access Control (Odoo 18)

Category-based security for contacts (`res.partner`) and centralized filtering of
contact / user selection fields.

## Concepts

| Object | Purpose |
|---|---|
| **Access level** (user form, "Contacts Access") | *none* = standard Odoo (default, nothing changes at install) · **Restricted** = only granted categories · **All Contacts** · **Administrator** (configures everything) |
| **Access category** (`contact.category`) | Admin-defined group of contacts. *Manual* (contacts are tagged) or *Rule-based* (static domain, e.g. `customer_rank > 0`). A contact can belong to many. |
| **Access line** (`contact.category.access`) | Users and/or groups + rights on one category: read (always), Edit, Create, Delete, Archive. Create and Archive require Edit. |
| **Field filter** (`contact.field.filter`) | For one many2one / many2many field to `res.partner` or `res.users` of any model: which categories / user groups can be selected. Optionally enforced on save. |

## How it is enforced

* Record rules on `res.partner` (read / write / create / unlink) for the Restricted level.
  Their domain is computed by `ir.rule._eval_context()['contact_access_domain']`, cached by
  Odoo per user, mode and active companies, and invalidated whenever categories, access
  lines or user groups change. Every ORM path honours them: search, read, RPC,
  `name_search`, `read_group`, export, @mentions.
* Rules are OR-ed with other group rules and AND-ed with the global multi-company rule.
* Always readable for restricted users: partners of internal users (required, because
  `res.users` inherits partner rules through `_inherits`), company partners, and the
  user's own commercial entity. Own partner is always editable (preferences).
* Child contacts and addresses inherit the manual categories of their commercial entity
  (`_commercial_fields`); rule-based categories also match through `commercial_partner_id`.
* Python guards only where a rule cannot express the requirement: archive right, adding /
  removing categories, moving a contact under another parent, and default category on
  create (context default, otherwise the first creatable manual category by sequence).
* Field filters are AND-ed into the field domain during view post-processing
  (`ir.ui.view._postprocess_tag_field`, also inside embedded sub-views; search views are
  left untouched). Enforcement uses `_validate_fields` and skips superuser operations.

## Known limitations

* Code running as superuser (`sudo()`: website, portal signup, mail gateway, some reports)
  bypasses record rules, as everywhere in Odoo.
* The display name of a hidden contact is still shown on documents the user can read
  (Odoo reads many2one names as superuser by design); opening the contact is refused.
* A restricted user cannot see hidden duplicates, so e.g. `find_or_create` by email may
  create a second contact in the user's default category.
* Field filters are global (same for every user) and apply after a page reload.
* Restricted users need at least one category with Create to create contacts (incl.
  quick-create, CRM lead conversion, new email recipients).

## Recommendations

* Grant `base.group_allow_export` (Extra Rights / Export) only to trusted users.
* With large contact tables, disable PostgreSQL JIT (`jit = off`), which otherwise adds
  hundreds of milliseconds of compilation to OR-heavy rule queries.

## Tests

```
odoo-bin -d <db> -u contact_access_control --test-tags /contact_access_control
```

The `contact_access_flows` tests (sale, purchase, invoice, CRM, stock) run when those
applications are installed and are skipped otherwise.
