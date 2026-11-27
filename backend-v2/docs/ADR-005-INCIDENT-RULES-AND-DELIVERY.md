# ADR-005 · Incident rules, deduplication and delivery

**Status** — Proposed for project owner review.

## Current behavior

The private ingestion app accepts an already-confirmed event. Identical UUID
replays return the same incident. A changed payload for that UUID returns 409.
PostgreSQL commits the incident and outbox row together. The publisher command
locks one due row, POSTs three identifiers over HTTPS, and schedules failed
attempts with a delay capped at five minutes. The existing public incident
status updates are audited. See the [Phase 3 contract](phases/03-incident-ingestion.md).

## Proposed decision

- Run a separate rules workload after gateway attribution and assignment
  revalidation. Keep the inference v1 request and response unchanged. Bind the
  rule evaluation to organization, site, camera, source epoch, assignment
  revision, verification generation and versioned policy. Drop stale epochs
  and out-of-order observations. Restart confirmation when the source or
  assignment changes.
- Start with the missing-helmet rule. Require an unambiguous person/head
  observation and an eligible model whose approved class map supports the rule.
  Use valid geometry and stable person association before deciding
  `compliant`, `violation` or `unknown`. Occlusion, missing required
  observations, unsupported labels and ambiguous associations yield `unknown`.
  Confidence and geometry thresholds require model-specific calibration.
- For a synthetic pilot, propose three violating observations within two
  seconds from the same tracked person to confirm an episode. Propose three
  compliant observations within two seconds to end it. Unknown observations
  do not create a violation or establish compliance. After a gap longer than
  two seconds, a source reconnect or assignment change, reset the observation
  window. Use generated tracks in automated tests. These timings are proposed
  test starting points.
- Keep episode identity separate from event delivery identity. Persist the
  event UUID and immutable payload before sending. Reuse both after a timeout
  or restart. Serialize episode creation per tenant, camera, policy version,
  rule and track. Keep duplicate prevention within a camera; cross-camera
  person linking requires its own decision. The current incident admin flow
  stays `open → acknowledged → resolved`.
- Give rules workloads a dedicated authenticated identity scoped to permitted
  camera/site/organization tuples. Check active scope on write; the existing
  trusted bearer and resource-join checks alone cannot enforce separate
  workload grants. Isolate the publisher identity and database grants from the
  rules writer and business API. Enforce HTTPS, bounded request deadlines and
  operator-owned endpoints.
- Keep at-least-once delivery. The receiver records acceptance durably before
  acknowledging. Duplicate event IDs return the previous receipt when the
  immutable identifiers match. On permanent errors or an exhausted retry
  budget, quarantine the row with a redacted reason. Operator replay keeps the
  original ID. Propose stopping after ten attempts or thirty minutes,
  whichever comes first, and seven days of receipt/idempotency retention for
  the test pilot. Review these values with
  the notification replay horizon in ADR-007.

An isolated Compose test checks the current HTTPS retry contract with a
disposable receiver. It does not set or exercise a PPE confirmation policy.
Single-frame incident creation was considered and rejected because ambiguous
frames cannot establish a violation. Exactly-once transport was considered;
receiver-side idempotency covers acknowledgement loss with simpler recovery.

## Acceptance and rollback

Test unknown and ambiguous frames, recovered and expired episodes, stale
assignments, concurrent duplicate confirmation, scoped identity rotation and
revocation, transaction rollback, acknowledgement loss, worker/receiver
restart, quarantine and replay. Verify that retry and replay preserve the
event identifier and that one event yields one durable receipt. Disable the
rules workload and publisher schedule to roll back. Keep incident, outbox and
receipt records available for reconciliation.

Approval is required for the rule and association semantics, pilot window and
calibration criteria, workload scope and credential lifecycle, and the delivery,
quarantine and idempotency budgets. Live activation remains a separate decision.
