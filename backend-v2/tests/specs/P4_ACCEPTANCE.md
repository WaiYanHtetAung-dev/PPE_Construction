# Phase 4 Acceptance Checklist — RTSP ingest, frame sampling, camera health and AI integration

> STATUS: PLANNED — do not assume implementation or test success.
> These case descriptions are **not proof** of executed tests. Update status/evidence after automation or manual validation.

| Case | Status | Evidence / link |
| --- | --- | --- |
| P4-01 — Secure stream aliases | Not run | — |
| P4-02 — Bad URL rejected | Not run | — |
| P4-03 — Camera online status | Not run | — |
| P4-04 — Camera disconnect | Not run | — |
| P4-05 — Reconnect and recovery | Not run | — |
| P4-06 — Ingest flood / overload | Not run | — |
| P4-07 — Malformed media | Not run | — |
| P4-08 — Per-camera fairness | Not run | — |
| P4-09 — Scaled camera trial | Not run | — |
| P4-10 — VPN/reverse network policy | Not run | — |

## Given / When / Then scenarios

### P4-01 — Secure stream aliases
- **Given:** Site camera has stream_ref
- **When:** Request provision to media service
- **Then:** Only trusted alias resolved; API never sees RTSP password
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-02 — Bad URL rejected
- **Given:** Untrusted caller submits HTTP/RTSP/private URL as alias
- **When:** Create/provision camera
- **Then:** Rejected without SSRF or fetching URL
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-03 — Camera online status
- **Given:** Test RTSP camera returns frames
- **When:** Start streaming and observe heartbeats
- **Then:** Online state with measured timestamp
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-04 — Camera disconnect
- **Given:** Streaming camera is active
- **When:** Disconnect camera/source
- **Then:** Health becomes offline, retries bounded, worker survives
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-05 — Reconnect and recovery
- **Given:** Camera is offline
- **When:** Restore camera
- **Then:** Reconnect automatically and resume frames without duplicate stream
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-06 — Ingest flood / overload
- **Given:** Frames arrive faster than inference capacity
- **When:** Sustain high stream rate
- **Then:** Bounded memory/queues with documented drop policy
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-07 — Malformed media
- **Given:** Invalid or unsupported media input
- **When:** Decode/process stream
- **Then:** Isolated failure; no API crash, clear error
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-08 — Per-camera fairness
- **Given:** Multiple cameras under load
- **When:** Observe frame processing
- **Then:** No starvation beyond agreed fairness target
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-09 — Scaled camera trial
- **Given:** Representative camera recordings and network profiles
- **When:** Run 50, then 100 streams using agreed FPS settings
- **Then:** Record GPU FPS, P95 latency, drops, resource usage vs agreed SLO
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD

### P4-10 — VPN/reverse network policy
- **Given:** Network topology has been approved
- **When:** Attempt unauthorized server→camera or outbound-only flow
- **Then:** Only documented tunnel/relay connections succeed
- **Automation owner / test path:** TBD
- **Result (Pass / Fail / Not run):** Not run
- **Evidence / environment / date:** TBD
