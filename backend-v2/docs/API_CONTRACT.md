# PPE Construction V2 — Public API Contract v1 (implemented subset)

Base URL: `/api/v1` (served only behind HTTPS in production).
Header: `Authorization: Bearer <opaque-token>`. Login is public; all org endpoints require membership.
Versioning: `/api/v1` is stable. OpenAPI schema at `/openapi.json` and Swagger at `/docs` **only when** `ENABLE_API_DOCS=true`.

| Method | Path | Access | Current status |
|---|---|---|---|
| GET | `/health/live` | public | implemented |
| GET | `/health/ready` | public | implemented; DB probe |
| POST | `/api/v1/auth/login` | public | implemented |
| POST | `/api/v1/auth/logout` | logged-in | implemented |
| GET | `/api/v1/auth/me` | logged-in | implemented |
| GET | `/api/v1/organizations/{org_id}/sites` | member | implemented |
| POST | `/api/v1/organizations/{org_id}/sites` | admin | implemented |
| GET | `/api/v1/organizations/{org_id}/sites/{site_id}/cameras` | member | implemented |
| POST | `/api/v1/organizations/{org_id}/sites/{site_id}/cameras` | admin | implemented |
| GET | `/api/v1/organizations/{org_id}/incidents?limit=50&offset=0` | member | implemented |
| GET | `/api/v1/organizations/{org_id}/models?limit=50&offset=0` | admin | implemented |
| GET | `/api/v1/organizations/{org_id}/models/{model_version_id}` | admin | implemented |
| POST | `/api/v1/platform/model-versions` | platform publisher | implemented |
| GET | `/api/v1/organizations/{org_id}/cameras/{camera_id}/model` | admin | implemented |
| PUT | `/api/v1/organizations/{org_id}/cameras/{camera_id}/model` | admin | implemented |
| GET | `/api/v1/organizations/{org_id}/cameras/{camera_id}/model/history` | admin | implemented |
| POST | `/internal/v1/inference-results` | mTLS/service identity | planned, NOT public |
| GET | `/api/v1/organizations/{org_id}/incidents/{incident_id}` | member | planned |
| POST | `/api/v1/organizations/{org_id}/incidents/{incident_id}/ack` | operator/admin | planned |

## Example

`POST /api/v1/auth/login`

```json
{"email":"admin@ppe.example","password":"<password>"}
```

Result: `{"access_token":"<opaque-token>","token_type":"bearer","expires_at":"..."}`.
Never log/store the raw bearer token; only its SHA-256 digest is persisted for session lookup.

`POST /api/v1/organizations/<org_id>/sites`

```json
{"name":"Building A","description":"Main entrance and west wing"}
```

`POST /api/v1/organizations/<org_id>/sites/<site_id>/cameras`

```json
{"name":"Gate 01","stream_ref":"stream:building-a/gate-01","enabled":true}
```

`stream_ref` is an **opaque, nonsecret** alias resolved inside the Media Gateway. Never submit `rtsp://user:pass@host` to this API.

## Security rules

### Organization model catalog

The organization catalog serves the shared eligible model versions after checking
admin membership in the requested organization. List results include `items`,
`total`, `limit` and `offset`, ordered by model key and version as text. The
page size is 1 to 100 and the default is 50. Detail takes a model version UUID.
Both endpoints return only `id`, `model_key` and `version` for each model.
Missing or expired sessions return `401`. Missing organization access or an
unknown or ineligible version returns `404`. Invalid query values or version IDs
return `422`.

### Camera model assignment

GET returns `revision` and `model_version` with the selected version's ID,
model key and version. An unassigned camera returns `model_version: null`.
Existing selections start at revision 0 and remain visible as current selection.

PUT accepts `expected_revision` and `model_version_id` (UUID or null to unassign).
Use a previously selected eligible version ID to roll back. A stale revision
returns 409. Repeating the current eligible selection at the current revision
does not write history or advance the revision. A successful change advances the
revision and commits the selection, history and audit event in one transaction.

GET history returns newest revisions first, with `limit` (default 50, maximum 100)
and optional exclusive `before_revision`. History includes previous and new
model IDs, actor ID and timestamp. A camera outside the requested organization
or unavailable model version returns 404. These endpoints require organization
admin membership and validate camera ownership through its site.

### Platform model registration

`POST /api/v1/platform/model-versions` accepts the metadata below. Configure
`MODEL_ARTIFACT_NAMESPACE=approved` to allow keys under `approved/`. An unset
namespace rejects registration. Keys are relative slash-separated identifiers.

```json
{
  "model_key": "ppe",
  "version": "1.0.0",
  "artifact_ref": "approved/ppe/1.0.0/model.bin",
  "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "class_map": {"worker": "person", "hard hat": "helmet"}
}
```

`201` returns the version ID, model key, version and `inference_eligible: false`.
The class map uses original labels as keys and inference v1 canonical classes
as values. Registration validates metadata and records a platform audit event
atomically. Artifact availability and byte-level verification are separate.
`401` means authentication failed, `403` means the platform grant is missing,
`409` means the global key/version already exists and `422` means invalid metadata.
Published metadata is immutable. Submit a new version for a metadata change.

Publisher administration uses `python -m app.scripts.platform_publishers grant <user-uuid>`
or `revoke <user-uuid>` from a restricted operator environment. Use individually
attributable PostgreSQL login roles that are members of `ppe_publisher_admin`.
A DBA provisions that group and its access to read user IDs and active flags,
read/insert/delete publisher grants and append platform audit events. The API
runtime role needs read-only access to publisher grants and the eligibility view,
and insert access to registry and audit rows. See [artifact verification](MODEL_ARTIFACT_VERIFICATION.md). Keep table ownership and DDL with the migration role.
Use restricted deployment credentials for these roles. CLI audit records use
the PostgreSQL login as actor.

- There is no automatic default admin/password; bootstrap via console command.
- No public inference/write-events route; service-to-service identity will be designed separately.
- Every organization-scoped DB query must verify membership; camera queries must also verify that the site belongs to the org.
- `viewer` cannot create sites/cameras. All API actions require server-side validation.
- Reject camera URLs and arbitrary HTTP URLs to mitigate SSRF/credential disclosure.
- Login rate limiting, MFA/SSO, refresh/session rotation, audit append service, per-camera RBAC, and API gateway protection are **not implemented**; required before production exposure.
