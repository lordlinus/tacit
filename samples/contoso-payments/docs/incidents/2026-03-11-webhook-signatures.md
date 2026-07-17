# Incident 2026-03-11: staging webhook signature failures

**Severity:** SEV-3 (staging only) · **Duration:** 13 days intermittent ·
**Author:** maya@contoso.com

## Summary

From 2026-02-26, bank settlement webhooks in **staging** failed signature
verification roughly 100% of the time, while production and local dev were
fine. Because staging consumers retry with backoff, the queue depth alarm
only fired on 2026-03-11.

## Timeline

- 02-26: Platform team fronts staging with Azure Application Gateway (WAF v2).
- 02-26 → 03-11: settlement events silently pile up in staging DLQ.
- 03-11 14:20 SGT: queue alarm fires; on-call reproduces `401 bad signature`.
- 03-11 16:45: root cause found; fix merged 17:10.

## Root cause

Application Gateway **normalizes request header names to lowercase**. The
webhook handler read the signature with an exact-case dictionary lookup on
the raw ASGI scope:

```python
headers = dict(request.scope["headers"])
signature = headers.get(b"X-Contoso-Signature")  # None behind the gateway
```

The bank sends `X-Contoso-Signature`; the gateway delivers
`x-contoso-signature`; the lookup missed; verification failed. Local dev and
production (no gateway at the time) preserved case, which is why it "worked
everywhere but staging".

## Fix

Read headers through Starlette's case-insensitive `request.headers` mapping
(commit `f3a9c21`). A regression test posts the webhook with lowercased
header names.

## Lessons

1. Treat HTTP header names as case-insensitive **everywhere**; any proxy may
   rewrite them (RFC 9110 §5.1 allows it).
2. A staging-only failure after an infra change is an infra-interaction bug
   until proven otherwise.
3. DLQ depth needs an alarm threshold measured in hours, not days.
