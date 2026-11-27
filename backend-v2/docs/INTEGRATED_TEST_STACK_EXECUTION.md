# PPE Construction V2 — Integrated Testing Stack Execution Plan

Status: IMPLEMENTATION TASK; not evidence of completion or deployment.
Requested scope: finish a reproducible non-production integration of React frontend, FastAPI backend, PostgreSQL, synthetic ONNX inference, and outbound-only media transport on the existing feature branch.
Baseline: 7fab0e2 (feature/frontend-v2-integration). Do not reset local changes.

Use the [disposable Compose lab](SYNTHETIC_COMPOSE.md) for the integrated
browser, PostgreSQL, outbound media and independent synthetic ONNX path.
The lab covers the existing incident read and status API with seeded fixtures.
Detection-to-incident policy and authorized evidence remain under ADR-005 and
ADR-007. The linked GitHub workflow records execution evidence for each commit.

## Required result

One documented, repeatable **disposable** test environment in which a user can log in, select an authorized organization, register/view a demo camera, observe a synthesized outbound media stream, receive model-agnostic detections from a separate ONNX worker, see a deduplicated incident, inspect authorized evidence and receive an incident status update. Failure cases must be tested, not merely described. No live CCTV, commercial model or production deployment implied.

## Architecture and network boundary

- Camera/NVR emits RTSP within the site LAN. An on-site relay/publisher reads RTSP and initiates outbound encrypted/authenticated media publishing to cloud ingest (SRT is the chosen prototype transport).
- Central server must **not** establish a route/session to private CCTV endpoints. No site inbound DST-NAT or RTSP port forwarding. Ordinary site outbound SNAT and established/related return traffic may be used.
- A router alone cannot transform RTSP pull into outbound publish; require a publisher process, unless the NVR can push a supported protocol by itself.
- Central media ingress distributes only authenticated publisher streams; bind publisher identity to allowed stream paths. Do not trust path text as identity.
- Video plane (ingest, decoder, sampler, ONNX worker) is separate from FastAPI business API and PostgreSQL. Keep local MP4 fixture decoder/test support intact.
- Browser never receives RTSP credentials, internal service tokens, artifact locations, or raw storage keys.
- Never proxy untrusted user-provided RTSP/HTTP URLs, local file paths or network addresses. All access is by scoped internal aliases.
- Use pinned images/dependencies, non-root users, health checks, limits, ephemeral disposable secrets and isolated networks for the test stack; do not expose PostgreSQL or inference worker publicly.

## Required vertical slices (commit each independently)

1. **Inventory and gap report.** Read backend-v2/AGENTS.md, current API/inference contracts, DECISIONS.md, PRODUCTION_READINESS.md, frontend-v2, media_gateway, inference_worker, compose files and existing CI. Mark real vs synthetic support accurately. Document exact run commands and environment requirements.
2. **Disposable Compose test stack.** Add a dedicated compose file (do not repurpose existing local postgres compose): PostgreSQL, FastAPI, inference worker, central media ingress, isolated synthetic site publisher, and static/frontend service or development proxy with same-origin /api/v1. Verify DB health/migrations and service startup. Avoid production credentials and external camera addresses.
3. **Network media adapter.** Keep local MP4 decoder as-is; add bounded, cancellable, allowlisted ingest adapter for decoded frames from authenticated central stream aliases. Validate stream dimensions, timestamps, identity, disconnect/reconnect, resource caps and queue cleanup. Fail closed on authorization loss; preserve ADR-009 assignment snapshots and verification-generation fencing.
4. **Inference.** Use approved synthetic ONNX fixture only for full integration tests; preserve versioned contract, eligibility check and independent worker boundary. Never claim real Finalboss accuracy or readiness without approved checkpoint/export/corpus and parity evaluation.
5. **Incident/evidence/notifications.** Propose ADR-005 and ADR-007 for human approval, implement only decisions already approved; otherwise isolate a synthetic test-only vertical slice. Verify idempotent private ingestion, PPE association policies, transactional incident/outbox writes, retry/dead-letter behavior and tenant-isolated evidence. Use private test object storage with retention/expiry tests. Realtime notifications must have auth and reconnect/replay handling.
6. **Frontend.** Complete login/logout/session expiry, organization isolation, camera status, model assignment display, incidents and evidence with accessible loading/error/empty states. Use same-origin API; browser playback requires authorized short-lived session/path, not RTSP URLs. Use real backend responses in integration mode, no silently substituted mock production values.
7. **Verification and handoff.** Run backend tests, isolated PostgreSQL migration+rollback rehearsal, contract checks, frontend type/build and Playwright/suitable browser E2E, synthetic stream disconnect/reconnect and unauthorized access, ONNX integration, and evidence/notification replay. Record commands, actual exit statuses, logs/report links, known gaps and test limitations. Upgrade to 3/6/10 synthetic streams first; representative 50–100 streams and pilot remain separate approval gates.

## Acceptance script outline

- Start disposable stack from a clean state with one documented command sequence and pinned versions.
- API readiness succeeds only after PostgreSQL is actually reachable and schema migrated.
- Login via frontend, switch organization, verify cross-tenant reads/writes are denied, verify expired session blocked.
- Start synthetic on-site outbound publisher and see authorized stream online on dashboard. Shut it off; verify offline and no stale frames/results; restart and verify bounded recovery.
- Gateway authorizes camera/model using scoped snapshot, dispatches frames through separate ONNX service, then correlates results with correct camera/org/model revision.
- A controlled synthetic PPE violation creates exactly one incident within the configured dedup window, associated test evidence, outbox event and authenticated frontend notification. Retry delivery does not create duplicate incident or double-notify.
- Revoke model, camera grant or publisher credential; pending and late responses must not emit detections/incidents after revocation. Verify secrets redacted.
- `docker compose down` must not delete persistent non-test data. Destructive volume cleanup must be an explicit separate command scoped to the disposable stack.

## Git hygiene (mandatory)

- Work on `feature/frontend-v2-integration`; fetch remote before working; inspect `git status`; do not discard uncommitted human changes.
- For each completed slice, commit code + tests + docs together, with meaningful message; push to `origin feature/frontend-v2-integration`.
- After each push verify the remote branch HEAD SHA and the relevant CI jobs. If push or tests fail, report exact error; never claim success.
- Keep README/runbook/status/acceptance documents synchronized with what was actually run. Don't merge to main or deploy production without human sign-off.
- GitHub connector commits update remote directly; local clone still needs `git pull --ff-only origin feature/frontend-v2-integration` after checking for uncommitted changes.

## Human approval gates

ADR-005, ADR-006, ADR-007 and ADR-008 must be reviewed and approved for the intended scope. Real NVR camera access, site networking, model rights and corpus, evidence privacy/retention, performance SLOs, PITR recovery objectives, staging and production deployment each require separate authorization. A finished synthetic testing stack is NOT equivalent to production readiness.
