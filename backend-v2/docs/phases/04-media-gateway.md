# Phase 4 — RTSP ingest, frame sampling, camera health and AI integration

**Status:** Bounded handoff, source sampling and reconnect logic implemented. Real RTSP decoding, live camera health and inference integration remain planned.

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
stall, reconnect and cancellation paths.

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
