# ADR-007 · Evidence access, retention and notifications

**Status** — Proposed for project owner review.

## Current behavior and dependency

The database has incident-linked evidence metadata. There is no production
evidence store, download route or notification consumer. ADR-005 supplies the
incident event identity and delivery contract. Evidence and notification
receivers must tolerate event replay.

## Proposed decision

- Start synthetic acceptance with one generated JPEG per incident, capped at
  1 MiB. The isolated evidence writer validates the incident, tenant and
  camera binding against authoritative state, verifies media bytes and
  SHA-256, strips metadata and writes to a private object store with
  operator-controlled keys. Store the checksum, size, media type, expiry
  and lifecycle state with the incident reference. Handle incomplete uploads
  and orphaned objects with a bounded reconciliation job.
- For the initial access model, allow organization admins to fetch incident
  evidence through an authenticated same-origin endpoint addressed by
  opaque incident and evidence IDs. Check organization membership and the
  resource chain on every request. Treat missing and unauthorized resources
  alike. Deny expired, quarantined, and deleted assets. Stream bounded
  bytes with `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
  Audit access using the actor and evidence ID. Keep object keys, credentials
  and media content out of logs, notifications and incident list payloads.
- Keep real-image capture disabled until the owner approves who can access
  evidence, how long it is kept, who can place or release a hold, when all
  object versions and backups expire, and how deletion completion is audited.
  Expiry first blocks new reads. The deletion job then removes object versions
  according to the approved policy and records the outcome. Preserve holds
  and retry recoverable storage failures. Use injected clocks and generated
  bytes to prove expiry and deletion in tests.
- Persist an in-app notification only after accepting a scoped ADR-005
  event. Deduplicate by organization and event ID. Return a successful
  publish acknowledgement only after committing the notification or
  confirming an identical existing receipt. Include incident ID, event
  type and time. An authorized member can read the organization's incident
  notifications; evidence access is separately checked.
- Start with an authenticated, paginated feed and an organization-bound
  cursor. Validate membership on every poll, clear state on organization
  changes and replay after the last authorized cursor on reconnect. Report
  an expired cursor explicitly and require a fresh authorized read. Set the
  replay horizon alongside ADR-005 idempotency retention. External delivery
  channels require approved recipient and delivery policies.

The alternatives considered were browser-facing presigned object URLs and
WebSockets. A bounded same-origin download can recheck current membership on
every request and keeps storage credentials and URLs private. The polling feed
allows durable replay and reuses current request authentication.

## Acceptance and rollback

Test wrong-tenant and revoked access, expired assets, checksum mismatch,
orphan cleanup, legal hold and deletion retries using synthetic content.
Test notification replay after acknowledgement loss, viewer/admin separation,
organization switching, cursor reuse across organizations, and expired
sessions and cursors. Disable evidence writes, downloads and the notification
consumer to roll back. Keep stored assets and delivery state available for
authorized reconciliation under the approved retention policy.

Approval is required for evidence roles, media handling, storage provider and
privacy policy, retention and holds, and notification audience and replay
horizon. Production images and external notification delivery require
separate authorization.
