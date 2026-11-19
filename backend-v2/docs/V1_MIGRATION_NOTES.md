# Legacy PPE_Construction (V1) → Backend V2 mapping

Based on the supplied `PPE_Construction-main.zip` and the starter schema. **No data migration has been executed**. V1 remains unchanged.

| V1 source | V2 concept | Data handling / caveat |
|---|---|---|
| `users` | `users`, `organization_memberships` | Map usernames to verified email identities; DO NOT assume IDs/roles map automatically. Require controlled credential reset or approved migration. |
| `sessions` | `session_tokens` | **Do not** migrate raw V1 tokens into V2; revoke and create new sessions. |
| `settings` | Future `site_policies` | Map per-site thresholds only after policy schema defined. |
| `cameras` (`rtsp_url`) | `sites`, `cameras` (`stream_ref`) | Create verified site assignments and nonsecret stream aliases; move RTSP secret to vault/media service. |
| `events` (`thumbnail_b64`) | `incidents`, `evidence_assets` | Verify images, create objects and checksums, store object keys. Source events may lack incident lifecycle/model version metadata; mark unknown explicitly. |
| `models/finalboss.pt` | Future inference service model registry | Record controlled artifact URI, digest, version and class map; do not store weight in API repo. |
| V1 live camera threads/global job dict | Future independent media/worker services | No direct in-memory state migration; build persistent job state and controlled cutover. |

## Migration strategy

1. Inventory V1 DB **read-only**; backup with restore verification. Capture row counts, hashes and retention constraints.
2. Decide organization/site mapping, username→email enrollment, existing camera permissions and event mapping. Get owner approval for any irreversibly ambiguous record.
3. Create a deterministic, repeatable **dry-run** translator on an offline V1 copy. Make it idempotent; record per-row outcome, reasons for skipped rows, image object checksum, errors.
4. Compare source/target counts and sampled incident/evidence records; keep mapping ledger and rollback plan.
5. Shadow mode: V1 keeps serving; V2 ingests only test/shadow traffic with no duplicate production notifications.
6. Staged cutover by camera/site under explicit approval; monitor alert parity/false positives, network, CPU/GPU, security logs and rollback criteria.
7. Revoke V1 sessions, rotate affected secrets, retain archive according to approved policy.

## Never infer

A Base64 thumbnail is not necessarily the complete evidence source. A V1 `UNSECURE` event is not necessarily a V2 `incident` with clean start/end semantics. Missing model version and time-zone information must be represented as unknown, not guessed.
