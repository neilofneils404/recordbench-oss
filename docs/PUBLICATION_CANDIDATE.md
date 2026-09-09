# CI publication candidate isolation

The application CI job fetches the exact PR head (or pushed commit) separately
from its integration checkout. A full fetch can also create refs for unrelated
branches. Running the generic scanner with `--all` in that shared fetch made
unrelated branch history part of the candidate result.

`scripts/check-publication-candidate.py` now verifies the expected HEAD and
tracked checkout, then uses the existing pre-push guard to inspect an isolated
copy of the explicit candidate object. Every ancestor remains included. Tag
pushes use the original tag object, verify its peeled commit against expected
HEAD, and retain annotated/nested-tag inspection. No residue rule is relaxed.

The generic scanner and the installed pre-push hook keep their existing
behavior. Repository-wide gitleaks history scanning remains separate and
unchanged. This CI check is evidence about the candidate, not an audit of every
branch in the repository and not a substitute for pre-publication inspection.

`tests/test_publication_candidate.py` exercises unrelated-history isolation,
removed residue in candidate ancestors, modified/wrong checkouts, unsupported
refs, and tag metadata/target checks using synthetic local repositories.
Existing pre-push/tag/publication tests remain applicable. No remote is contacted
by these tests, and failed inspection does not print matched values.
