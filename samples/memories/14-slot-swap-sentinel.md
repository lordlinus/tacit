---
path: /gotchas/slot-swap-config-sentinel.md
category: gotcha
tags: deploy, app-service, config
---
# After every slot swap, bump CONTOSO_APP_CONFIG_SENTINEL

App Service slot swaps exchange code but the app caches config at startup, so
production keeps serving with stale configuration until workers recycle (up
to ~20h). The pipeline bumps `CONTOSO_APP_CONFIG_SENTINEL` on every deploy,
which triggers a worker recycle and a config re-read.

Deploying manually? Bump the sentinel yourself or new feature flags and
rotated secrets silently don't take. Release flow: `azd deploy` to staging →
30 min bake → `az webapp deployment slot swap` → sentinel bump. Rollback is
swap-back + bump again. Migrations are expand-contract; never ship the
contract step with its expand step.
