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
