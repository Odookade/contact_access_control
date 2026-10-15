# Contact Access Control (Odoo 20)

Category-based security for contacts (`res.partner`) and centralized filtering of
contact / user selection fields.

## Concepts

| Object | Purpose |
|---|---|
| **Access level** (user form, "Contacts Access") | *none* = standard Odoo (default, nothing changes at install) · **Restricted** = only granted categories · **All Contacts** · **Administrator** (configures everything) |
| **Access category** (`contact.category`) | Admin-defined group of contacts. *Manual* (contacts are tagged) or *Rule-based* (static domain, e.g. `customer_rank > 0`). A contact can belong to many. |
| **Access line** (`contact.category.access`) | Users and/or groups + rights on one category: read (always), Edit, Create, Delete, Archive. Create and Archive require Edit. |
| **Field filter** (`contact.field.filter`) | For one many2one / many2many field to `res.partner` or `res.users` of any model: which categories / user groups can be selected. Optionally enforced on save. |

## How it is enforced (Odoo 20 `ir.access`)

Odoo 20 replaced `ir.model.access` and `ir.rule` with a single model, `ir.access`:
*permissions* (with a group) are OR-ed, *restrictions* (without a group) are AND-ed
(`Model._access_domain`). Base and business apps grant unconditional permissions on
`res.partner` (e.g. `base.group_user` read, partner manager / sales / purchase
update-create-delete), so a group permission can never narrow access. Therefore:

* `security/ir.access.csv` declares the *capability*: a `cud` permission for the
  Restricted level (plus the module's own models);
* the *scope* is a restriction AND-ed by `res.partner._access_domain()`, the 20.0
  replacement of `_check_access`, overridden the same way core does for cross-module
  conditions (`mail.mail`, quotation documents). It is not a global `ir.access` record
  on purpose: such a record would reference names that only exist while this module's
  code is loaded, and would break contact access for every user otherwise (observed with
  a partial registry load during `-u base`).

The scope is `TRUE` for users outside the Restricted level or with All Contacts, the
category scope otherwise. It is cached per user and active companies, like
`_access_domain` itself, and invalidated through `ir.access._clear_caches()` whenever
categories, access lines or group memberships change.

* Every ORM path honours the restrictions: search, read, RPC, `name_search`, read_group,
  export, @mentions, write, create, unlink.
* Always readable for restricted users: partners of internal users (required, because
  `res.users` inherits partner restrictions through `_inherits`), company partners, and
  the user's own commercial entity. Own partner is always editable (preferences).
* Child contacts and addresses inherit the manual categories of their commercial entity
  (`_commercial_fields`); rule-based categories also match through `commercial_partner_id`.
* Python guards only where an access domain cannot express the requirement: archive right,
  adding / removing categories, moving a contact under another parent, and default category
  on create (context default, otherwise the first creatable manual category by sequence).
* Field filters are AND-ed into the field domain during view post-processing
  (`ir.ui.view._postprocess_tag_field`, also inside embedded sub-views; search views are
  left untouched). Enforcement uses `_validate_fields` and skips superuser operations.

## Odoo 20 specifics (vs. the 19.0 version)

* `ir.rule` / `ir.model.access` → `ir.access` + `_access_domain` override (see above); `registry.clear_cache()` →
  `ir.access._clear_caches()` and `transaction.invalidate_ormcache()`; `tools.ormcache` →
  `api.ormcache`.
* An access level is a regular (not *light*) group, like the Sales roles: users placed in
  it get the *User* role, which Odoo 20 also requires to show the Contacts app menu.

## Odoo 19 specifics (vs. the 18.0 version)

* Access levels are a `res.groups.privilege` ("Contacts Access", next to base's Contact and
  Export privileges); groups use `user_ids` / `all_group_ids`.
* Domains use `odoo.fields.Domain`; SQL constraints use `models.Constraint`.
* Categories are a *commercial field* (synced downstream only). They are deliberately not a
  `_synced_commercial_field`, which in 19 would also push a child's edit up to its parent.
* Odoo 19 only syncs *set* commercial values: a contact attached to an uncategorized parent
  keeps its own categories.
* Name searches on the "All Access Categories" field arrive as `('field', 'any', domain)`.
* A new child contact can update its parent's address / VAT as the current user, which is
  why Create keeps requiring Edit.

## Known limitations

* Code running as superuser (`sudo()`: website, portal signup, mail gateway, some reports)
  bypasses access restrictions, as everywhere in Odoo.
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
