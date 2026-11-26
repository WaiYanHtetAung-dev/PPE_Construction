# Phase 4 — RTSP ingest, frame sampling, camera health and AI integration

**Status:** Synthetic MP4 decoding, bounded sampling and authenticated inference v1 dispatch implemented. Live RTSP, camera health and service orchestration remain planned.

## Scope and deliverables

Introduce MediaMTX/FFmpeg or GStreamer pipeline separated from FastAPI, secure secrets, bounded sampling and reconnect policy.

`media_gateway.frame_queue.FrameQueue` provides an in-process handoff for trusted
samplers. It keeps one pending immutable frame per camera. New samples replace
that camera's pending frame without moving its turn. Once served, a camera
rejoins at the tail with its next sample. Offers exceeding the available slots
or byte budget are rejected, preserving work already queued for other cameras.
Limits apply to pending payloads. The dispatcher must separately bound in-flight
work, and the decoder must bound its own buffers. Run
`python -m unittest tests.test_frame_queue` from `backend-v2` for synthetic
admission, ordering and concurrency checks.

`media_gateway.sampler.sample_camera` reads decoded frames from a trusted source
adapter with a per-read timeout, samples by monotonic time and reconnects after
EOF, I/O errors or stalled reads with capped exponential backoff. Source
adapters own connection setup and cleanup and must bound their own setup time.
`python -m unittest tests.test_media_sampler` exercises synthetic disconnect,
stall, reconnect and cancellation paths. It also runs one, two and three
simultaneous synthetic samplers and checks camera attribution and shutdown.
These unit fixtures emit decoded bytes in process.

### Synthetic video decoder integration

`local_video_source` launches a PyAV/FFmpeg child process for trusted local MP4
fixtures. It passes decoded RGB24 frames and presentation timestamps through a
bounded pipe. The sampler retains camera ID, dimensions, frame index, receive
time (UTC), monotonic sampling time, configured interval and reconnect epoch.
Presentation timestamps are strictly ordered within an epoch. Reopening a file
starts a new epoch with its own timestamp origin. Fixture playback is unpaced;
sampling uses media time, so the test does not measure live camera throughput.

Generate fixtures only in a disposable test directory. They contain visible
frame counters and presentation time markers at 10, 24 and 30 FPS. Tests check
0.2-second sampling within one source-frame period, concurrent attribution,
corrupt input, EOF reconnect, timeout recovery and child-process cleanup.
The MP4 demuxer uses a local file handle with external data references disabled.
No live input or model is required.

From `backend-v2` in the workspace Python environment, run:

```text
python -m pip install -r requirements-dev.txt -r requirements-inference-cpu.txt -r requirements-media-test.txt
python scripts/ci_checks.py media
```

On Windows, point `TEMP` and `TMP` at an ignored D: workspace directory before
running so fixture files stay on D:. Both CI providers call the same command.
GitLab runner execution remains **NOT TESTED**. RTSP, inference and end-to-end
pilot acceptance with live inputs require separate tests.

### Synthetic media to inference v1

`InferenceDispatcher` drains the existing frame queue one frame at a time. It
requires a trusted camera-to-assignment binding containing the organization,
site, camera, model version UUID, key/version and original-to-canonical class
map. Never build this binding from frame input. A future control-plane client
must supply current assignments and refresh them when they change.

The gateway validates frame metadata, stages one bounded PNG under a generated
`frames/<uuid>.png` key, and submits the existing v1 request to a configured
HTTPS worker origin with its dedicated ingress credential. The worker must see
the same queue staging directory through its read-only frame mount. Provision
the directory and its parents for trusted writers only, with group read access
for the worker where separate users share the mount. Use disposable storage for
test runs. A process crash can leave its one in-flight PNG for the operator to
clean up before reuse.

Inference v1 carries the frame/request IDs and model key/version. The gateway
correlates the response against those exact values and retains org/site/camera,
timestamps, and the assigned model version UUID in its own result envelope.
The worker independently verifies the eligible version, manifest signature and
artifact digest. The response does not repeat the model UUID, tenant metadata,
or raw numeric class indices. The gateway validates original and canonical
class labels, finite confidence and latency, and in-frame bounding boxes.

One in-flight request and the existing newest-frame-per-camera queue limit
memory and staged filenames. The worker request has a deadline and a 512 KiB
response budget. Failed frames are dropped and the next sample may proceed.
If staged-file cleanup fails, dispatch stops on that instance. Logs include
the request UUID and normalized outcome. They exclude credentials, paths,
frames, and response bodies.

From `backend-v2`, install `requirements-dev.txt`,
`requirements-inference-cpu.txt` and `requirements-media-test.txt`, then run
`python scripts/ci_checks.py media`. Both CI providers execute this command.
Mock transport tests cover validation, authentication responses, timeout and
backpressure. Linux integration exercises PyAV, the real inference ASGI app,
signature/eligibility checks and ONNX Runtime using temporary test-only model
artifacts and an in-process authority. Verified-worker tests skip on Windows
because the existing secure artifact reader relies on POSIX directory file
descriptors. The test signer and leases are scoped to temporary fixtures and
make no registry writes. Live performance remains **NOT TESTED**.

Windows D: validation with Python 3.14 ran the shared media command with 17
passes and two POSIX worker skips. The separate command
`python -m pytest -q tests/test_onnx_cpu.py tests/test_inference_contract.py tests/test_contract_fixtures.py`
recorded 12 passes and eight POSIX skips, including actual CPU ONNX inference
outside the verified-worker path.

### Phase 4 control-plane camera assignment sync

The [approved ADR-009](../DECISIONS.md#adr-009-proposal--workload-scoped-camera-assignment-snapshots)
defines workload credentials, atomic assignment/evidence reads, and the 5 s
poll / 2 s deadline / 10 s lifetime pilot policy. The private entry point is
`app.assignment_snapshot:from_environment`. The listener reads a PostgreSQL DSN
from `ASSIGNMENT_DATABASE_URL_FILE`. Provision a dedicated database login with
only `SELECT` on `public.gateway_snapshot_credentials` and
`public.gateway_snapshot_assignments`. The application creates read-only DB
transactions. Keep the listener on a private network behind HTTPS. Apply
Alembic revision `4e29c61bd0fa` in the disposable PostgreSQL test environment.

`app.scripts.gateway_credentials` exposes transactional `provision`, `rotate`
and `revoke` operator primitives. A separate login in the deployment-provisioned
`ppe_assignment_operator` group needs access to the gateway tables, scoped
camera/site lookup columns and platform audit inserts. Keep this trusted
operator outside gateway and listener runtimes. Call the primitives in a
transaction and transfer the returned token to a protected secret store after
commit. Rotation retains at most one previous active credential with expiry
clipped to five minutes. Never log bearer tokens or database URLs.

Bind an `AssignmentResolver` to the frame queue and pass the same resolver to
`InferenceDispatcher`. Start the resolver's `run()` task alongside samplers.
The resolver applies expiry and revocation fences before queue admission, at
send and before returning a result. Consumers that await or queue results
after return must recheck `resolver.current(camera_id, result.assignment_epoch)`
at actual emission. Linux uses the suspend-inclusive `CLOCK_BOOTTIME` clock.
Other platforms require an explicit clock with equivalent behavior. Synthetic
tests use a fake clock. No live revocation latency or throughput is measured.

From `backend-v2`, run the current-boundary regression checks with:

```text
python -m pytest -q tests/test_api.py tests/test_camera_models.py tests/test_model_catalog.py tests/test_model_verification.py tests/test_inference_worker.py
python -m pytest -q tests/test_assignment_snapshot.py
python scripts/ci_checks.py media
python scripts/check_architecture.py
python scripts/verify_contracts.py
```

Windows D: validation reported 19 passes and 24 skips for the focused backend
tests, and 17 passes and two POSIX skips for the media suite. The focused backend
skips require POSIX file handling or a disposable PostgreSQL service. The
architecture and snapshot checks passed. GitHub and GitLab use the existing
shared backend and PostgreSQL jobs for these checks. Gateway integration tests
use mocked snapshot and inference transports to force races. The media suite
additionally runs the existing independent real ONNX worker checks on Linux.

### Disposable HTTPS stack acceptance

`python scripts/ci_checks.py stack` runs the integrated suite from `backend-v2`
after `python scripts/ci_checks.py postgres` has migrated and checked the
disposable database. Install `requirements-dev.txt`,
`requirements-inference-cpu.txt` and `requirements-media-test.txt`. The command
validates the same disposable `APP_ENV=ci` / `ppe_ci` connection as the shared
PostgreSQL job. It requires Linux and a runner with permission to create two
read-only bind mounts beneath its temporary directory (root with mount
capability, or passwordless `sudo -n mount/umount`). Missing mount capability
fails the selected acceptance job. GitLab can use this command on a dedicated
capable runner; the standard GitLab container job does not invoke it.

The harness serves assignment and eligibility FastAPI apps on ephemeral
loopback HTTPS ports and starts the verified ONNX worker as a separate
subprocess. All listeners trust a generated test CA through explicit TLS
configuration. The worker uses `ELIGIBILITY_AUTHORITY_CA_FILE` for that CA and
receives no DB or CI credentials. The listener and authority receive distinct
read-only database roles. Generated video, ONNX graphs, manifests and runtime
secrets are held in a temporary directory. The gateway writes frames through
one alias, while the worker reads them and the signed model artifacts through
read-only mounts. Listeners, mounts and files are cleaned up by the harness;
the CI job owns and tears down its PostgreSQL service.

The test reports `PPE_STACK_METRICS` with elapsed switch, revoke, timeout and
recovery observations and inference header latency. It also reports offered
samples and pre-dispatch losses (including saturation, replacement and policy
discard). The 5/2/10 s policy and fake-clock tests remain the reference for
boundary behavior. A single loopback run provides synthetic evidence; live
camera throughput and cross-site revocation timing remain **NOT TESTED**.

The same stack command also runs three bounded switch/revoke/reverify cycles
while all three synthetic decoders and the inference consumer stay active.
Each cycle holds a real worker response until affected assignment epochs have
been fenced, checks that an unaffected camera continues to emit, and requires
a new verification generation before accepting recovered work.
`PPE_STACK_REPEATED` reports each cycle's elapsed observations, revocation
median and maximum, and per-camera offers, drops, queued frames at shutdown,
and emitted results. It includes individual test harness counters for
discarded responses and polling cadence. The fixture is unpaced, so frame
counts and drops characterize this workload only.

The stack repeats the same three switches and revocations with paced replay
(`PPE_STACK_PACED`). It preserves presentation timestamps across loop
boundaries and prevents catch-up bursts. The fixture rates are 10, 24 and
30 FPS, with a 0.2 s media-time sampling target. The report includes measured
effective source FPS, which can be lower because the decoder reopens at each
clip boundary and the replay does not catch up.

The test accounts for every pre-dispatch loss as policy rejection, pending
frame replacement, or queue purge. Replacements are separated into dispatcher
idle, dispatcher occupied, and intentionally held response windows. Purges
are separated by whether they occurred within the controlled revocation
window. Dispatcher occupancy is an observed condition, not a causal estimate
of production inference capacity. Frames still queued at shutdown and
in-flight responses discarded by the assignment fence are reported separately.

The stack emits eight `PPE_STACK_SAMPLING` windows for sampling every 0.2 s
and 0.4 s. Run four consecutive pairs with an alternating order: 0.2/0.4,
0.4/0.2, 0.2/0.4 and 0.4/0.2. Each uses the same three paced inputs, model
assignments, worker and queue limits. Each runs after a three-second warm-up and records
12 seconds of steady-state measurements. The comparison has no test-imposed
response hold, switch, or revocation. Per-camera sample age is wall-clock
elapsed time from the sampler's monotonic timestamp through queueing, staging,
HTTPS inference and response validation. It excludes decoding and source time.
Record source FPS in each arm to expose decoder throughput variation.
`PPE_STACK_SAMPLING_PAIRED` compares totals within each pair and reports
per-camera medians across windows. The age aggregate is the median of the
window medians. These four pairs are evidence for a synthetic pilot choice;
they do not estimate production latency or a confidence interval.

## Design decisions and prerequisites

Decide cloud-pull WireGuard vs site outbound relay, actual codecs/bitrates, validation cameras, track bounded GPU workload.

**Critical note:** No unsupported assertion that 50–100 cameras already pass capacity. Benchmark with real profiles.

## Execution plan

1. Read architecture, ERD and relevant current API + inference contracts. Compare real code to planned endpoints.
2. Write an ADR/design proposal for any missing ownership, security, consistency or networking decision.
3. Define typed contracts + migration plan before implementation.
4. Implement smallest vertical slice on feature branch and add tests with mocked external services.
5. Run local tests and CI, inspect PostgreSQL migration and contract diffs.
6. Complete documented acceptance cases, attach evidence, list blockers and obtain review before next phase.

## Acceptance test cases

| ID | Test | Given | When | Expected result |
|---|---|---|---|---|
| P4-01 | Secure stream aliases | Site camera has stream_ref | Request provision to media service | Only trusted alias resolved; API never sees RTSP password |
| P4-02 | Bad URL rejected | Untrusted caller submits HTTP/RTSP/private URL as alias | Create/provision camera | Rejected without SSRF or fetching URL |
| P4-03 | Camera online status | Test RTSP camera returns frames | Start streaming and observe heartbeats | Online state with measured timestamp |
| P4-04 | Camera disconnect | Streaming camera is active | Disconnect camera/source | Health becomes offline, retries bounded, worker survives |
| P4-05 | Reconnect and recovery | Camera is offline | Restore camera | Reconnect automatically and resume frames without duplicate stream |
| P4-06 | Ingest flood / overload | Frames arrive faster than inference capacity | Sustain high stream rate | Bounded memory/queues with documented drop policy |
| P4-07 | Malformed media | Invalid or unsupported media input | Decode/process stream | Isolated failure; no API crash, clear error |
| P4-08 | Per-camera fairness | Multiple cameras under load | Observe frame processing | No starvation beyond agreed fairness target |
| P4-09 | Scaled camera trial | Representative camera recordings and network profiles | Run 50, then 100 streams using agreed FPS settings | Record GPU FPS, P95 latency, drops, resource usage vs agreed SLO |
| P4-10 | VPN/reverse network policy | Network topology has been approved | Attempt unauthorized server→camera or outbound-only flow | Only documented tunnel/relay connections succeed |

## Exit criteria

- [ ] All required cases for this phase run and their results are documented (not just specified).
- [ ] Negative auth/tenant/secret cases included for changed routes and workers.
- [ ] CI green, PostgreSQL migrations validated, contracts reviewed and exported if changed.
- [ ] A reviewer approves the security, privacy and migration impacts.
- [ ] Handoff and rollback notes recorded in `docs/PR_TEMPLATE.md`.

See also `tests/specs/P4_ACCEPTANCE.md` for scenario checkboxes and execution evidence template.
