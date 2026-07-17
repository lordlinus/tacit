# Deploying Contoso Payments

Releases go out with `azd deploy` to the **staging slot**, bake for 30
minutes under synthetic traffic, then swap to production.

## Steps

```bash
azd deploy --environment staging
./scripts/smoke.sh staging
az webapp deployment slot swap -g rg-payments -n app-payments \
    --slot staging --target-slot production
```

## The slot-swap config gotcha

App Service slot swaps exchange *code* but slot-sticky settings stay put, and
the app **caches config at startup**. After a swap the production slot keeps
serving with the *old* cached configuration until the worker recycles. The
fix baked into our pipeline: bump `CONTOSO_APP_CONFIG_SENTINEL` on every
deploy. The app watches that one setting; changing it triggers an App Service
restart notification, which recycles workers and re-reads all settings.

If you deploy manually and skip the sentinel bump, production runs mixed
old-config/new-code until the next natural recycle (up to ~20 hours). This
bit us twice before the sentinel existed. Symptoms: new feature flags
ignored, webhook secret rotation "not taking".

## Rollback

Swap back (`--slot production --target-slot staging`) and bump the sentinel
again. Database migrations are expand-contract; never ship a contract step in
the same release as its expand step.
