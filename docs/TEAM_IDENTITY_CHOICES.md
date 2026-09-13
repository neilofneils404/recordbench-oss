# Choose the intended account for a grant

**Case team** and **Team groups** show each person as **Name (sign-in username)**.
The person selector starts at **Choose a person** and requires an explicit
selection. People may share a display name; compare their sign-in usernames
before adding someone. The resulting member list and confirmation identify the
selected account in the same form, including retained grants for disabled local
accounts.

No account receives access merely by being first in the list. The existing
owner/administrator, CSRF, provider eligibility and live membership checks still
control the submitted principal. A successful grant to the wrong eligible person
is an incorrect grant, not evidence that an unassigned person bypassed
authorization. Remove that person's grant and inspect any other direct or group
grants before assigning the intended account.

For the first synthetic practice matter:

1. Have two separate reviewer accounts sign in once.
2. Select the intended reviewer's name and username in **Case team**. Check that
   the confirmation and roster identify that same account.
3. In separate signed-in sessions, confirm the intended reviewer can open the
   matter and the unassigned reviewer cannot.
4. Remove the intended reviewer's last grant while that session stays open.
   Confirm the same session can no longer open the matter or download its work.

A reusable group affects every matter explicitly granted to that group.
Removing one grant preserves other valid grants; see [Team groups](TEAM_GROUPS.md).
The setup checklist records that a current teammate opened the matter. Its
progress does not certify the negative access check or source/model quality.

## Synthetic regression

`tests/test_team_identity_choices.py` creates two local reviewers with identical
display names. It verifies the required empty selection, distinct username
labels, rejection of an empty submitted target, grants to the second named
candidate, visible account confirmations, and unassigned/revoked access denial
for both direct and group grants. It repeats with maximum-length local account
names and usernames so successful changes cannot redirect to an invalid page.

Both existing browser acceptance scripts use three independent sign-in sessions
and duplicate reviewer display names. They choose a non-first reviewer by its
exact visible account label and verify the roster before testing access. The
group script also covers mixed direct/group grants and last-grant revocation.

```console
python -m pytest -q tests/test_team_identity_choices.py tests/test_team_groups.py tests/test_team_onboarding.py
python scripts/qa-people-browser.py --artifacts /tmp/recordbench-people-acceptance
python scripts/qa-team-groups-browser.py --artifacts /tmp/recordbench-groups-acceptance
```

These runners create disposable synthetic nodes and do not modify an existing
installation. Browser prerequisites and the gateway-scope distinction are in
[Browser asset origin](BROWSER_ASSET_ORIGIN.md).
