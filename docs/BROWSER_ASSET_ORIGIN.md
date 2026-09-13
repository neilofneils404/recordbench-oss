# Browser assets through the HTTPS gateway

The sign-in page, authenticated workbench and synthetic review bench load their
styles, scripts, icons and demo audio from the browser's current origin. Static
template links use the mounted static route's path, preserving its root prefix.
They do not derive an external scheme or port from the backend request.

This keeps an HTTPS address on a nondefault port usable when a gateway forwards
HTTP to the application with a portless Host header. It does not expand trusted
proxy addresses, trust browser identity headers, publish another service, or
change the TLS and secure-cookie requirements in [Security model](SECURITY_MODEL.md).
The rest of the application still assumes the documented deployment routes;
the static-path prefix regression does not promise complete subpath hosting.

## Synthetic regression

`tests/test_same_origin_assets.py` renders all four templates that reference
static assets with an HTTP backend request and a portless Host. It resolves and
fetches every referenced asset through an external HTTPS origin on port 9443,
checks its content type, and repeats with a mounted root prefix. The synthetic
templates need no accounts, models, container engine or existing installation.

`scripts/qa-people-browser.py` uses a disposable application and actual browser
on loopback HTTPS. The application receives a simulated backend HTTP scope while
the browser keeps the HTTPS address and random port. Its companion browser script
checks that stylesheets loaded, scripts stay on the same origin, static requests
succeed, and the Activity drawer responds to a click. It also checks the People
and case-team workflow described in [Team identity choices](TEAM_IDENTITY_CHOICES.md).
This simulation does not run the installed gateway container.

With the contributor dependencies installed:

```console
python -m pytest -q tests/test_same_origin_assets.py tests/test_branding.py
python scripts/qa-people-browser.py --artifacts /tmp/recordbench-people-acceptance
```

The browser runner also requires Node, OpenSSL, and an installed Playwright
browser. `PLAYWRIGHT_MODULE` may identify an existing package;
`RECORDBENCH_QA_BROWSER_CHANNEL=chrome` selects installed Chrome. Generated
screenshots must remain outside the checkout.

## Installed-node check

Open the installation's actual HTTPS address, including its port, and sign in.
Confirm that the workbench is styled and **Activity** opens and closes. Repeat
the synthetic account access check on that installation. A reachable sign-in
page or healthy service endpoint alone does not establish that authenticated
pages, static resources and browser interactions work through its gateway.
