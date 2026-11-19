# Phase 2.5 inference security boundary

The API, artifact verifier, eligibility authority and inference worker are
separate processes. The authority has a PostgreSQL read-only login. The worker
has only its internal HTTP credentials, read-only release and frame mounts,
and the pinned signer public key. It receives no database URL, signing key,
publisher, verifier, revoker or migration credentials.

## Internal API v1

- `POST /internal/v1/model-eligibility` on the authority accepts `model_key`,
  `model_version` and a per-call UUID `nonce`. Bearer authentication uses the
  authority token. A 200 response echoes the identity and nonce with
  `schema_version: "1.0"`, `model_version_id`, `artifact_ref`,
  `artifact_sha256`, `manifest_sha256`, `signer_key_sha256`,
  `verification_id`, `issued_at` and `expires_at`. These are server UTC
  timestamps. Leases are capped at 10 seconds and never exceed evidence expiry.
  Responses are non-cacheable. No current eligibility returns 404. Database
  unavailability returns 503.
- `POST /internal/v1/infer` on the worker accepts and returns the existing
  [inference JSON v1](INFERENCE_CONTRACT.md). It uses a different bearer token
  from the authority. Missing/invalid credentials return 401, malformed input
  or an out-of-namespace frame key returns 422, and unavailable inference
  returns a generic 503. Neither path is mounted on the business application.

Only an authenticated, trusted media producer may call inference. That producer
must authorize the camera and frame before dispatch. The worker's frame mount
and namespace bound its storage access. For isolated workloads, provision
separate frame namespaces, mounts and ingress credentials. These routes are
internal and provide no public tenant authorization surface.

## Verification, lease and runtime

1. Fetch a live eligibility lease without caching. Require the requested version,
   matching nonce and a positive bounded lifetime. Apply an absolute deadline
   and a monotonic deadline measured from before the authority request.
2. Read signed sidecars from approved storage using a pinned Ed25519 key. Match
   the signed version, registered reference and digest against live evidence.
   Stream artifact bytes into a capped immutable snapshot while hashing. Compare
   the actual SHA-256 and the manifest and signer fingerprints against the
   evidence committed by the verifier.
3. Renew the live lease before loading. Require the same evidence identity.
   The trusted adapter's `load(bytes)` context manager receives only the exact
   snapshot checked by the worker. It must never reopen an artifact reference.
4. Fetch a fresh lease again just before invoking the adapter. Expiry, change
   of evidence, confirmed revocation or a disconnected authority fails closed.
   The context manager unloads the model on success and failure. There is no
   cross-request lease or model cache. Already-running inference is bounded by
   deployment timeouts rather than asynchronously cancelled. The final
   authority lookup is the admission point for new inference.

A trusted runtime factory uses `module:factory` and implements
`load(artifact: bytes)` and `infer(model, frame: bytes, request)`. It must use
an approved model format and release resources in the context manager. The
service returns 503 without an adapter. CI uses a synthetic adapter and does not
load production assets or require a GPU.

The opt-in [Phase 2.6 CPU adapter](PHASE_2_6_ACCEPTANCE.md) accepts the fixed Finalboss ONNX candidate profile. Its real-checkpoint export and parity validation remain gated.

## Development Compose

Use the opt-in profile with the existing base Compose file. Run Alembic through
`e5c19a74d620` on a disposable database before starting. Provision a dedicated
authority login with only the grants below and store its DSN in the authority
secret file. The worker must never receive that file.

```sql
GRANT SELECT ON public.eligible_model_versions TO ppe_eligibility_reader;
GRANT SELECT (id, model_key, version, artifact_ref, artifact_sha256)
    ON public.model_versions TO ppe_eligibility_reader;
GRANT SELECT (id, model_version_id, manifest_sha256, signer_key_sha256, expires_at)
    ON public.model_verifications TO ppe_eligibility_reader;
```

Create a local ignored `.inference-dev/` directory with distinct random
`ingress.token` and `eligibility.token` files, `eligibility-db.url`, raw
32-byte `signer.pub`, and the `models/`, `frames/`, and `runtime/` mount
directories. Ensure the required files are readable by container UID 10001.
Use signed test artifacts under `models/approved/` and frame keys under
`frames/frames/`. Set `INFERENCE_DEV_RUNTIME_FACTORY` when a trusted test
adapter is available. Mount directories must already exist.

```sh
docker compose -f compose.yaml -f compose.inference.yaml --profile inference config -q
docker compose -f compose.yaml -f compose.inference.yaml --profile inference up --build
```

No worker or authority port is published. The trusted caller joins the
`inference_ingress` network. Compose HTTP is for the isolated dev authority
network. Production requires HTTPS with verified server certificates, network
policies, distinct rotatable workload secrets, clock synchronization, approved
immutable artifact storage, safe runtime adapter, bounded ingress and adapter
timeouts, and capacity validation. Database role and mount provisioning require
operational review.

## Schema-compatible rollback

Disable dispatch, drain existing requests, and stop only `inference-worker`
and `eligibility-authority`. Keep the business API, PostgreSQL schema
`e5c19a74d620` and existing assignment, audit and verification rows. No Alembic
downgrade is required. The PostgreSQL test shuts down the authority, verifies
business login and assignment read still work, and checks the evidence and
schema after rollback. Production adapter drain and deployment rollback
procedures still need operational rehearsal.
