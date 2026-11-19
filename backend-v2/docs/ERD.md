# PPE Construction V2 — ERD (Phase 1)

Source-to-target reconciliation:
- V1 `users`, `sessions` → V2 `users`, `session_tokens`, `organization_memberships`.
- V1 `cameras` → V2 `sites` + `cameras` with stream aliases; RTSP secrets NEVER stored in `stream_ref`.
- V1 `events` → V2 `incidents` and `evidence_assets`; Base64 evidence lives outside Postgres.
- V1 `settings` → planned `site_policies` (not yet implemented).
- New `model_versions` + `camera_model_assignments` make AI version selection independent of API.

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ ORGANIZATION_MEMBERSHIPS : has
    USERS ||--o{ ORGANIZATION_MEMBERSHIPS : joins
    USERS ||--o{ SESSION_TOKENS : authenticates
    ORGANIZATIONS ||--o{ SITES : owns
    SITES ||--o{ CAMERAS : contains
    CAMERAS ||--o| CAMERA_MODEL_ASSIGNMENTS : selects
    MODEL_VERSIONS ||--o{ CAMERA_MODEL_ASSIGNMENTS : used_by
    ORGANIZATIONS ||--o{ INCIDENTS : records
    SITES ||--o{ INCIDENTS : occurs_at
    CAMERAS ||--o{ INCIDENTS : observed_by
    MODEL_VERSIONS ||--o{ INCIDENTS : classified_by
    INCIDENTS ||--o{ EVIDENCE_ASSETS : evidence
    ORGANIZATIONS ||--o{ AUDIT_LOGS : records
    USERS ||--o{ AUDIT_LOGS : performs
    ORGANIZATIONS { string id PK
        string name
    }
    USERS { string id PK
        string email UK
        string password_hash
    }
    ORGANIZATION_MEMBERSHIPS { string id PK
        string organization_id FK
        string user_id FK
        string role
    }
    SESSION_TOKENS { string token_hash PK
        string user_id FK
        datetime expires_at
        datetime revoked_at
    }
    SITES { string id PK
        string organization_id FK
        string name
    }
    CAMERAS { string id PK
        string site_id FK
        string name
        string stream_ref
        bool enabled
    }
    MODEL_VERSIONS { string id PK
        string model_key
        string version
        string artifact_ref
        string artifact_sha256
    }
    CAMERA_MODEL_ASSIGNMENTS { string camera_id PK,FK
        string model_version_id FK
    }
    INCIDENTS { string id PK
        string organization_id FK
        string site_id FK
        string camera_id FK
        string model_version_id FK
        string status
        string violation_type
    }
    EVIDENCE_ASSETS { string id PK
        string incident_id FK
        string object_key
        string media_type
    }
    AUDIT_LOGS { string id PK
        string organization_id FK
        string actor_user_id FK
        string action
    }
```

## Phase 2 camera assignment revision and history

`cameras.model_revision` persists the optimistic revision through unassignment.
Existing cameras start at revision 0 and retain their current selections.
`camera_model_history` has primary key `(camera_id, revision)` and stores
the organization, actor, previous and new version IDs, and timestamp.
PostgreSQL rejects UPDATE, DELETE and TRUNCATE on history. Referenced cameras,
organizations, users and versions therefore require a history retention policy
before hard deletion is introduced.

## Decisions still needed before final production cutover

1. Retention, legal requirements and deletion semantics for incident evidence.
2. Camera/site role matrix (admin/operator/viewer) and per-camera permissions.
3. Scale constraints: multi-site camera counts, device connectivity, frame-rate targets.
4. Incident deduplication, time-based hysteresis, per-person tracking IDs.
5. Site policies, notification receipts, job persistence and camera health are phase 2 tables.
6. Tenant consistency for incident site_id/camera_id needs validated service-level inserts or composite FKs; currently only authorized incident reads are implemented.
