---
path: /gotchas/webhook-header-casing.md
category: gotcha
tags: webhooks, staging, gateway, headers
---
# Webhook signatures fail in staging: gateway lowercases header names

Azure Application Gateway (fronting **staging only**) normalizes request
header names to lowercase, so the bank's `X-Contoso-Signature` arrives as
`x-contoso-signature`. Any exact-case header lookup breaks in staging while
working in prod and local dev — this burned 13 days in incident 2026-03-11.

Rule: always read headers via Starlette's case-insensitive `request.headers`,
never via `request.scope["headers"]`. If webhook signatures fail only in one
environment, suspect a proxy rewriting headers before suspecting the code.
Also: verification rejects >5 min clock skew — slept WSL2 VMs drift
(`sudo hwclock -s`).
