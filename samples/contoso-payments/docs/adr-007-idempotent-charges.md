# ADR-007: Idempotent charge creation via key table + transactional outbox

Status: accepted (2025-11-02)

## Context

Product teams retry aggressively on timeouts. The bank charges real money; a
double-submit is a customer-visible incident. We need exactly-once *effect*
over at-least-once *delivery*, without distributed transactions.

## Decision

1. **Idempotency-key table.** Every charge request carries an
   `Idempotency-Key` header. We reserve the key (INSERT ... ON CONFLICT DO
   NOTHING) before any side effect. A replayed key returns the stored
   response; an in-flight key (reserved, unresolved) returns 409 so the
   client backs off instead of racing.

2. **Transactional outbox.** The charge row and its `charge.created` outbox
   event are written in the same local transaction. A separate relay process
   publishes outbox rows to Service Bus and marks them published. Publishing
   inline (after commit) would lose events on crash; publishing before commit
   would emit events for rolled-back charges.

3. **Reconciler.** Keys reserved but unresolved for > 5 minutes are re-driven
   against the bank's charge-status endpoint (`GET /v2/charges?ref=`), which
   is itself idempotent. This repairs crashes between reservation and the
   bank call.

## Consequences

- Replays are cheap (one SELECT) and exact (byte-identical response).
- The outbox relay adds ~1s p50 event latency; consumers must tolerate it.
- Key TTL is 24h (bank constraint); clients must not reuse keys across days.
- The key table grows ~2M rows/day; partitioned by day, dropped after 7 days.
