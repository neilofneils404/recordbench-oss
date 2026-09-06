## User problem

Describe the review or operator problem this change addresses.

## Result

Describe the behavior after this change in plain language.

## Synthetic evidence

List the synthetic reproduction, automated tests, and any browser or clean-host
acceptance performed. Do not include private deployment output.

## Impact

- Security, authorization, or matter isolation:
- Storage, deletion, backup, or migration:
- Models, licensing, or offline operation:
- Operator documentation or recovery:

## Checklist

- [ ] All examples, fixtures, screenshots, and logs are synthetic and
      environment-neutral.
- [ ] No private identity, hostname, address, path, credential, certificate,
      data, transcript, runtime state, or deployment overlay is included.
- [ ] Behavioral changes include a regression test and applicable
      documentation.
- [ ] `make check` passes, or the exact bounded exception is explained.
- [ ] The publication sanitizer passes.
- [ ] The complete outgoing history passed the local pre-push check; PR text
      and attachments were separately inspected before upload.
- [ ] Before merge: final-commit GitHub Codex code/security reviews completed,
      all findings were reconciled, and required CI passed.
- [ ] No existing release tag was moved or rewritten.
