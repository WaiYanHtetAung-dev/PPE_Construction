# Model artifact verification

ADR-004 keeps registration and assignment in FastAPI. A separate Linux workload
verifies artifact bytes and provenance. Public API and inference v1 JSON are
unchanged. Registration returns `inference_eligible: false`.

## Release input

An authorized release signer publishes the artifact and two sidecars beside the
registered opaque key. For `approved/releases/model.bin` the sidecars are
`model.bin.manifest.json` and `model.bin.manifest.sig`. The latter contains the
64-byte Ed25519 signature over the exact JSON bytes. The JSON contains
`model_version_id`, `model_key`, `version`, `artifact_ref`, `artifact_sha256`,
`release_id`, `issued_at`, and `expires_at`. The time fields use timezone-aware
timestamps and the validity window is at most 24 hours.

Provision a read-only mount from the trusted release store and immutable
release files. The mount must exclude publisher write access to the backing
store. Keep the raw 32-byte pinned signer public key in separately controlled
configuration. Only the release signer holds the private key. Retain the signed
manifest and signature in the release archive for audit.

Set `MODEL_VERIFIER_ARTIFACT_ROOT`, `MODEL_ARTIFACT_NAMESPACE`,
`MODEL_VERIFIER_PUBLIC_KEY`, `MODEL_VERIFIER_MAX_BYTES` and verifier-specific
`DATABASE_URL`. Use an absolute trusted mount root. Run the verifier under a
bounded supervisor deadline and a restricted workload identity.

```
python -m app.scripts.model_artifact_verifier verify-promote <model-version-uuid>
python -m app.scripts.model_artifact_verifier revoke <model-version-uuid>
```

Verification opens only regular files beneath the approved namespace, verifies
the pinned signature and exact model binding, and compares the SHA-256 of the
actual bytes. It neither fetches arbitrary URLs nor loads a model. A failed
operation commits zero state or audit changes. Successful promotion and
revocation have transactional platform audit events.

## PostgreSQL role separation

Provision these NOLOGIN groups outside Alembic and grant membership to separately
attributable logins. The migration owner owns schema objects and performs DDL.
Do not run FastAPI or verifier workloads as the owner or a superuser.

```sql
GRANT SELECT ON public.model_versions TO ppe_model_verifier;
GRANT EXECUTE ON FUNCTION public.promote_verified_model(
    text,text,text,text,text,timestamptz,timestamptz
) TO ppe_model_verifier;
GRANT EXECUTE ON FUNCTION public.revoke_verified_model(text) TO ppe_model_revoker;
GRANT SELECT ON public.eligible_model_versions TO ppe_app_runtime;
```

Retain runtime permissions for normal business operations and metadata
registration. The runtime and publisher must have zero write access to the
verification tables, and zero EXECUTE on promotion and revocation. The verifier
and revoker execute their functions without direct table writes. The verifier
database login is trusted to submit only evidence produced by the verifier
workload. Restrict its credentials to that workload and review effective
privileges, including role inheritance and ownership. Reserve
`ppe_publisher_admin` for the existing grant/revoke CLI.

## Expiry, revocation and rollout

Migration `e5c19a74d620` removes the old eligibility flag. Existing version and
assignment records survive. Versions require new verified evidence before
becoming eligible. Expiry and revocation exclude the version from catalog reads
and new assignments, including database-level assignment writes.

Existing assignment history is preserved. An affected camera must stop
dispatching to the revoked or expired model once its eligibility lease ends.
Operators can reassign to another verified version. The independent inference
service must resolve eligibility through an authenticated control path, refresh
only bounded leases, fail closed on stale or unavailable eligibility, and hash
the exact pinned bytes before deserializing or loading them. On checksum
mismatch it must refuse loading. The [independent inference worker](INFERENCE_SECURITY_INTEGRATION.md) implements the lease and byte checks. Production adapter, storage and lease configuration remain operational requirements.

Coordinate the schema upgrade with the new application version because earlier
Phase 2 application code expects the removed Boolean column. An application
rollback needs a schema-compatible build. Downgrading removes evidence and
restores all flags as false, so it requires backup and human review.
