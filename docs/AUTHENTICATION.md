# Authentication

RecordBench has three deployment modes. All use opaque server-side sessions,
CSRF protection, explicit matter membership, and attributed audit events.

## Local accounts

Local mode stores only Argon2id password hashes in an owner-only JSON file. The
login page never lists account names, errors do not reveal whether an account
exists, and repeated failures are rate-limited at both gateway and application
layers. At least one enabled administrator is required.

Manage accounts inside the tools container; do not edit hashes by hand:

```bash
docker compose --profile tools run --rm --no-deps account-admin \
  accounts list --file /run/recordbench-secrets/local-accounts.json
```

## OIDC

OIDC uses authorization code flow, PKCE, nonce/state, exact HTTPS issuer and
callback validation, signed ID tokens, a file-backed client secret, optional
group admission, and a separate administrator-group mapping. Administrator
roles are sealed into the short-lived server session; provider group changes
take effect at the next sign-in or session expiry. Register the final external origin plus
`/auth/oidc/callback`. Keep provider CA material and client secrets outside Git.

Automation can supply `--oidc-issuer`, `--oidc-client-id`,
`--oidc-allowed-groups`, and `--oidc-admin-groups`. Supply the client secret only
through an owner-readable file with `--oidc-client-secret-file`; never place it
in a command argument, environment example, or repository file.

## Kerberos

Kerberos uses an Apache `mod_auth_gssapi` proxy with an HTTP service keytab. The
gateway clears spoofable identity headers; Apache validates Negotiate, removes
the browser Authorization header, and adds the principal plus a shared secret.
The app revalidates the trusted boundary and resolves allowed/administrator
groups through the joined host’s SSSD NSS socket on every request.

Create the SPN/keytab for `HTTP/<recordbench-host>@<REALM>`, verify there is only
one SPN owner, use AES keys, protect the keytab at `0600`, and rotate it through
a planned outage. Browser integrated-auth policy and DNS must use the same final
hostname. Logging out closes RecordBench’s session; it cannot sign Windows out.

Automation can supply `--kerberos-realm`, `--kerberos-allowed-groups`,
`--kerberos-admin-groups`, and the owner-readable exported keytab through
`--kerberos-keytab`. The installer copies the keytab into its owner-only secret
boundary and never prints its contents.

Never expose the app or Kerberos proxy directly. Only the HTTPS gateway should
publish a host port.
