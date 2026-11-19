# Threat Model, Risks, and Unresolved Decisions

Status: **architecture design**, not completed security validation.

## Trust boundaries / protected assets

- **Human browser → Public API**: session bearer tokens, identity, organization membership, RBAC, CSRF/CORS posture (depending on future auth storage), rate limits.
- **API → PostgreSQL**: org-scoped writes, cross-tenant reference consistency, transaction isolation, migration safety.
- **API/Worker → Media Service**: credential access, stream alias allowlist, private network, SSRF prevention.
- **Media/AI → Event ingestion**: authenticated service identity, replay protection, idempotency and tamper-resistant evidence.
- **Evidence storage → Browser**: short-lived authorized download URLs, retention, redaction/privacy requirements.

## Risks to mitigate before production

| Risk | Current state | Required mitigation / test |
| --- | --- | --- |
| Unauthorized site/camera access | Membership checked for existing endpoints | Per-resource cross-tenant tests; future per-camera RBAC |
| Model version cross-tenant assignment | `model_versions` global | Choose registry ownership/publishing policy; test authorization |
| Model artifact attack | Metadata schema only | Allowlisted storage, checksum/signature, no arbitrary URL fetch |
| Camera SSRF | `stream_ref` regex implemented | Media gateway owns secret URL; public camera aliases reject private-IP/URL inputs. Inference frame `object_key` has no URL/traversal validator at Pydantic layer yet; trusted resolver must strictly allowlist namespace/path (design gate). |
| Token theft / brute force | Argon2 + hashed opaque sessions | TLS, login throttling, MFA/SSO as warranted, token revocation telemetry |
| Event spoofing / replay | No ingestion endpoint | mTLS or signed workload credentials; idempotent event_id, replay tests |
| Cross-org incident mix-up | Incident read filtering only | Validate org↔site↔camera ownership on every insert |
| Evidence leak | DB metadata only | Private bucket, signed access, deletion policy, access audit |
| Resource exhaustion | No video/worker in API | Queue bounds, input size limits, GPU/stream quotas |
| Availability and data loss | No backup drill | PITR/WAL backups, restore test, service monitoring |
| Unsafe decision automation | No model inference wired | Define review/escalation; run false positive/false negative evaluation |

## Required design decisions before implementation

- Organization-specific model ownership vs globally curated approved models.
- RBAC matrix for admins/operators/viewers (per organization/site/camera), access-revocation propagation.
- Evidence retention/deletion policy and handling of personal imagery under local regulation.
- Media topology: VPN server-pull vs onsite outbound-only relay; live preview target and stream budget.
- Model benchmark acceptance targets; validation data; what counts as an alert and when humans intervene.
- Incident lifecycle, duplicate suppression, track IDs, hysteresis, unknown/low-confidence states.
- Secrets manager / rotation, service identity, deployment domain and certificates.

## Operational hygiene

Never commit credentials, camera URLs containing passwords, private image samples, live model weights without approved distribution rights, or real access tokens. Rotate any V1 defaults/embedded credentials if they were ever used outside a local demo. Use generated non-sensitive fixtures in automated tests. No live site systems accessed by CI.
