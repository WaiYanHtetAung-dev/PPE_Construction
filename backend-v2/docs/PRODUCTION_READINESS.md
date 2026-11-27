# Production Release Gate — MUST be evidenced, not assumed

**This starter is not approved to deploy.** Check each box only with a linked test report/reviewer. No date or owner is pre-assigned.

## Identity and data isolation

- [ ] Role matrix signed off; no cross-tenant read/write across endpoints, jobs, reports, evidence URLs.
- [ ] TLS, session expiry/revocation, rate limiting, audit logging and break-glass account process verified.
- [ ] Internal service authentication, replay prevention, CORS/WebSocket policy, SSRF reviews.
- [ ] Secrets rotation, no public DB/Redis/object store access, SAST/SCA and dependency lock plan.

## Data and reliability

- [ ] All DB migrations reviewed and tested from blank DB + preexisting-data snapshot.
- [ ] Backups, retention, WAL/PITR approach, disaster restore drill and RPO/RTO targets signed off.
- [ ] Evidence object lifecycle, permissions, checksums and deleted/expired access tested.
- [ ] Duplicate incident delivery, transient worker outage, alert retry/dead-letter replay tested.

## Media and inference

- [ ] Camera site network trust/access approved, credentials protected, WAN VPN/relay flows documented.
- [ ] Model license and artifact provenance verified, baseline dataset documented.
- [ ] False negative/positive rates and unknown-state handling evaluated under representative conditions.
- [ ] 50–100 representative stream load scenario tested with measured metrics and agreed SLOs.
- [ ] GPU/CPU failure/recovery, camera disconnect/reconnect, restart/rollout, model rollback tested.

## User experience and operations

- [ ] UI human-in-the-loop review workflow and site alert escalation approved.
- [ ] Monitoring, tracing, dashboards, on-call contacts/escalation and runbooks reviewed.
- [ ] Canary releases, no double-notify in shadow mode, V1 rollback rehearsal done.
- [ ] Audit evidence, test result links and deployment approval recorded in PR/release notes.

**Release decision:** Pending; production sign-off must be explicit and recorded. Do not treat successful `pytest` as release authorization.

## Evidence and dependencies for roadmap steps 6–10

| Roadmap step | Available evidence | Required before release |
|---|---|---|
| 6 · Media gateway and CCTV | Disposable HTTPS/PostgreSQL/ONNX runs exercise assignment changes, revocation, decoder recovery and overlapping source outages. ADR-006 adds authenticated camera reads, a bounded browser clip and loopback RTSP/SRT acceptance. Backend CI covers the network sampler through ADR-009 and the independent ONNX worker, including revocation and re-verification. | Approve ADR-006 and pilot scope. In staging, verify site routing, the encrypted tunnel, private process isolation, credential rotation, codec compatibility and inference with approved site streams. |
| 7 · Evidence and realtime delivery | The public incident list has a browser smoke test with synthetic data. | Approve ADR-005 for incident-to-evidence integration and ADR-007 for retention and privacy. Verify evidence delivery and notification replay. |
| 8 · Capacity | Three- and six-camera synthetic runs measure per-camera throughput, result gaps and queue pressure. | Obtain approved representative fixtures and agree SLOs (ADR-008). Run the 50–100-stream trial and validate the approved model. |
| 9 · Security, monitoring and backup | CI exercises synthetic credential rotation, snapshot scope, TLS and database migrations. Pipeline timing is available in the synthetic report. | Demonstrate backup and restore, agree alert thresholds and the operator response, and complete the production security review. |
| 10 · Staging, UAT and release | Local browser smoke and disposable CI are reproducible from the runbook. | Record staging and UAT authorization, run the acceptance and rollback rehearsals, then obtain explicit production approval. |

Real Finalboss export and parity are tracked separately with the approved
artifact, checkpoint rights, locked toolchain and validation corpus requirements.
See [offline workflow acceptance](PHASE_2_6_ACCEPTANCE.md) and the
[synthetic evidence runbook](LOCAL_RUNBOOK.md#synthetic-pilot-diagnostics-in-a-browser).

Local ADR-006 checks cover cross-organization camera denial, requests after
logout, disabled cameras, database binding, H.264 clip encoding, and unsafe
source configuration rejection. On Windows, the loopback outbound test passed
with FFmpeg 9.1, MediaMTX 1.21.3 and Chromium. It verified encrypted publication,
wrong-path and wrong-passphrase denial, browser playback, metrics, offline clip
denial, and reconnection. The [outbound media workflow](../../.github/workflows/outbound-media-ci.yml)
runs the same acceptance test on Linux. Site router
rules, WAN media, production credentials and representative capacity have no
acceptance evidence from this slice.

The [disposable Compose run for `692fe00`](https://github.com/WaiYanHtetAung-dev/PPE_Construction/actions/runs/45965492216)
verified migrations, same-origin login and logout, tenant isolation, incident
status and audit persistence, authorized playback, and publisher disconnect
and recovery. The independent worker returned ten synthetic detections both
before the publisher stopped and after it recovered. The site network could
not reach the central RTSP reader. See the [lab runbook](SYNTHETIC_COMPOSE.md)
for the isolated incident replay test. Automatic incident rules, event
delivery, evidence policy and the production release gates remain open.
