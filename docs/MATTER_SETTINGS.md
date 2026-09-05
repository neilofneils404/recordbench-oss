# Matter settings and naming

Current contract for the matter name, updated September 5, 2026.

The matter owner or an application administrator can open **Settings → Rename
matter**, edit the name, and select **Save matter name**. All team members see
the saved name when they next navigate or refresh. An administrator can rename
without joining the team; the action is attributed to that administrator.
Ordinary members can read settings but cannot rename.

Names use the creation rules: 1–140 characters after Unicode NFC normalization
and trimming, with unsupported control/format characters rejected. Invalid
submitted text remains in the form for correction. The form is escaped normally
and fits a narrow viewport. Changing a name does not change the matter ID, URL,
owner, memberships, source files or versions, citations, conversations, saved
notes, Reports, processing jobs, or review period. New export requests use the
current name; already downloaded work product is not rewritten.

## Authorization and concurrent edits

`POST /matters/{slug}/rename` requires an authenticated owner/administrator,
valid CSRF, `name`, and `expected_name` from the displayed form. Nonmembers
receive 404; ordinary members receive 403. An already validated administrator
may use the existing explicit store-level override. Inside one SQLite immediate
transaction, the store rechecks an active principal and active matter, plus
active owner membership when not using administrator authority.

The store compares the current name with `expected_name` before saving. If it
has changed, the response is 409 with the current name, the proposed name still
in the input, and an instruction to review before submitting again. This is a
current-name comparison, not a full edit-history revision: changing a name away
and back to the displayed value does not create a conflict. Unrelated case
activity does not invalidate the form. Saving the same name makes no mutation
or additional successful rename audit event.

The name change and the content-free `matter.rename` audit commit atomically.
The event records actor, session/request, matter and owner/administrator role,
without recording old or new names. Audit failure rolls back the rename.
The operation uses existing schema; no source registry or search-index rewrite
is needed. Failed/inactive/deleted matters cannot be renamed.

Close matter still offers final export and requires deliberate exact-name
confirmation and no active work. Its name check and deletion claim now hold one
immediate transaction shared with rename, so another connection cannot change
the name between confirmation and the claim. An old-name confirmation after a
rename is rejected. Existing owner/administrator closure policy is unchanged.

## Verification and recovery

`tests/test_matter_rename.py` covers atomic rollback, attribution, permissions,
invalid names, separate-connection stale edits, lifecycle denial, source
identity, and the rename/close race. The race was reproduced before the
transaction change. `tests/test_matter_management.py` covers the surrounding
settings, administration, export, and deletion behavior.

`scripts/browser-accept-matter-rename.py` starts only an ephemeral loopback
application with synthetic proxy identities. It uses separate Chrome sessions
for owner/admin edits, checks the ordinary-member view and mobile layout,
uploads a source, saves a source-supported note, reopens its citation after
rename, downloads a renamed matter bundle, rejects old-name closure, and
confirms deletion using the new name. Its synthetic runtime is temporary;
only requested screenshots and the content-free result are retained.

Validation on September 5: the full application suite passed **749 tests** with
**9 environment-dependent skips**; the focused rename/management suite passed
30 tests. All **5 Chrome workflow checks** passed, including desktop conflict
recovery, mobile layout, export, and deliberate synthetic closure. Publication
scan, compilation, and diff whitespace checks passed.

Run with explicit Chrome and driver paths:

```sh
PYTHONPATH=src python scripts/browser-accept-matter-rename.py \
  --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver \
  --output /path/to/synthetic-results
```

No dependency, persistent-schema, or deployment configuration changes are
required. An older application can read the renamed matter and all existing
work using the same IDs. Rollback removes the rename interface but does not
restore an old name; an owner/admin can correct the name through this interface
before rolling back. No automatic deployment is part of this change.
