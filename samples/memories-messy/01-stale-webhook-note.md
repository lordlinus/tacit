---
path: /gotchas/webhook-staging-failures.md
category: gotcha
tags: webhooks, staging
---
# Webhook signatures failing in staging behind gateway — header issue?

Settlement webhooks 401 in staging but verify fine locally. Staging-only, so
probably an environment/secret mismatch. Check whether the webhook secret in
staging Key Vault rotated. (Unresolved.)
