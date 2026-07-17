---
path: /architecture/idempotent-charges.md
category: architecture
tags: idempotency, outbox, adr-007
---
# Charge idempotency (ADR-007): key table + transactional outbox

Retries are safe end-to-end by design:

1. `Idempotency-Key` header is **reserved** (INSERT ... ON CONFLICT DO
   NOTHING) before any side effect. Replayed key → stored byte-identical
   response; reserved-but-unresolved key → 409 so clients back off.
2. Charge row + `charge.created` outbox event are written in the **same
   transaction**; a relay publishes to Service Bus afterwards. Never publish
   inline (crash loses events) or pre-commit (emits for rolled-back charges).
3. A reconciler re-drives keys unresolved >5 min via the bank's idempotent
   charge-status endpoint, repairing crashes between reserve and bank call.

Constraints: key TTL 24h (bank rule — clients must not reuse keys across
days); key table is day-partitioned, dropped after 7 days; outbox adds ~1s
p50 event latency.
