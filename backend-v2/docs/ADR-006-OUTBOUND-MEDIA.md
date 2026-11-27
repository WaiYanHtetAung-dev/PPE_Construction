# ADR-006 · Outbound site media publishing

**Status: Proposed.** Implementation and synthetic acceptance may proceed on the
feature branch. Live connectivity, provisioning and deployment require approval.

## Decision and alternatives

A site publisher reads one provisioned RTSP source on the private CCTV LAN and
initiates an encrypted SRT connection to the central MediaMTX ingress. Use H.264
video for the first pilot. Defer audio, transcoding at the site and fan-out across
workers. Only the site publisher has the camera URL and camera credentials.
The router needs outbound reachability to the approved ingress and stateful
return traffic. Do not add a site port-forward or route to the CCTV subnet.

Central VPN pull would require the central service to initiate camera sessions.
Public RTSP forwarding would expose a private site listener. An outbound WebRTC
publisher would require ICE/TURN and different sender support. SRT allows a single
outbound transport while keeping ingestion separate from browser playback.

## Trust boundaries and identity

1. Provision a distinct publisher identity and high-entropy passphrase per stream.
   Configure MediaMTX `authInternalUsers` with a single exact `publish` path for
   that identity, the path's `srtPublishPassphrase`, `source: publisher`, and
   `overridePublisher: false`. Remove all default anonymous permissions. Use
   MediaMTX `read` identities limited to exact paths and a separate monitoring
   identity. A requested path carries no authority by itself.
2. Make only SRT UDP reachable by the publisher. Bind central RTSP TCP and
   metrics to trusted interfaces; in the same-host design bind them to loopback.
   This prevents a publisher bypassing SRT encryption through central RTSP.
   Disable unused protocols, recording and public control endpoints. Deny central
   egress to the CCTV LAN. The RTSP adapter accepts only an operator-configured
   central loopback IPv4 endpoint and exact paths, and has no camera LAN credentials.
3. Treat the SRT stream ID as visible connection metadata. Before exposing real
   credentials on an untrusted route, protect the SRT handshake with an
   outbound-initiated encrypted site tunnel restricted to the central ingress.
   Route only the ingress address and permit only SRT over that tunnel; do not
   advertise or forward the camera subnet. SRT still enforces its per-path
   passphrase. FFmpeg needs the publisher and camera URLs in its process arguments;
   run it under an isolated service identity with private PID visibility and
   process-argument logging disabled. Read secrets from protected runtime files.
4. The media service provisions a one-to-one camera UUID/opaque alias/ingress path
   binding outside the business database. The business API checks current human
   session, organization membership, camera ownership and enabled state before
   calling a private, bearer-authenticated loopback media service. The gateway
   requires both the configured camera ID and its expected database alias. The
   browser receives health fields and a bounded in-memory MP4 clip, without
   camera URLs, ingress credentials or reusable media tokens. Requests are
   checked for each clip; media already delivered cannot be retracted.
5. The RTSP adapter yields the existing `DecodedFrame` interface. Workload
   assignment polling, eligibility and result fencing still belong to ADR-009
   and inference v1. Browser preview has a separate bounded sampler and queue;
   it grants no authority to run inference or emit incidents. No migration is
   required by this slice.

## Observability and risks

Private MediaMTX metrics show stream availability and inbound bytes. Derive
ingest throughput from the inbound-byte rate. The media service exposes decoded
bytes and frames, reconnect attempts, queue drops and outstanding frames, and
sample-to-preview-buffer latency through authenticated `/internal/v1/metrics`.
Sample cadence intentionally omits some input frames; queue drops are counted
separately. Offline clips expire and the buffer is cleared on reconnect.

The browser plays an on-demand clip of up to two seconds. Continuous live
playback, alert thresholds, render and inference load at scale, WAN loss,
credential rotation with active sessions, and real-camera codecs require
separate acceptance. Host process isolation and a restricted egress route are
required controls because transport authentication does not address a stolen
publisher host or an exposed private listener.

## Reproduce the synthetic stack

The [workflow](../../.github/workflows/outbound-media-ci.yml) builds the existing
frontend, installs FFmpeg with libsrt and a checksum-pinned MediaMTX, and runs two
loopback MediaMTX instances. One is a fake CCTV RTSP LAN and the other accepts SRT
publication. The runner creates fresh credentials and ephemeral ports, then
exercises publisher identity/path and passphrase rejection, authorized browser
decoding, metrics, publisher loss and reconnect. The same test can run on a
developer machine with the tools installed and the frontend already built:

```powershell
Push-Location backend-v2
$env:PPE_OUTBOUND_RUN = '1'
$env:PPE_MEDIAMTX = (Resolve-Path 'D:\path\to\mediamtx.exe').Path
python -m pytest -q --tb=short tests/media_outbound_integration.py
Pop-Location
```

Use the existing [browser smoke setup](LOCAL_RUNBOOK.md#same-origin-browser-smoke-task-1),
install `requirements-media-test.txt` in the same environment, and use an
FFmpeg build with `libx264`, RTSP and `srt`. The loopback harness tests protocol
boundaries; it does not exercise a site firewall or the encrypted WAN tunnel.

The [backend workflow](../../.github/workflows/backend-v2-ci.yml) also sends a
decoded outbound frame through the ADR-009 resolver and the independent CPU
ONNX worker using signed synthetic fixtures. It exercises attribution, queued
frame purge, in-flight response rejection on revocation, continued inference on
a second camera and recovery after re-verification of the same model version.
To include this case in the integrated suite, run from `backend-v2` on Linux
with the disposable PostgreSQL and read-only mount prerequisites in
[the integrated stack runbook](INTEGRATED_TEST_STACK_EXECUTION.md):

```sh
python scripts/ci_checks.py postgres
PPE_MEDIAMTX=/absolute/path/to/mediamtx python scripts/ci_checks.py stack --report /tmp/synthetic-pilot.html
```

Look for `PPE_OUTBOUND_ONNX` in the test output. The existing MP4-only stack
command remains available when `PPE_MEDIAMTX` is unset.

## Next pilot deployment, after approval

1. Record one to three approved camera IDs and site subnets. Allocate a central
   ingress address, SRT UDP port, distinct stream paths, and site publisher
   identities. Review the route allowlist with network operations. Confirm
   central has no route to the CCTV subnet and no site inbound rule is created.
2. Generate an operator-only MediaMTX configuration with the ACL and encryption
   controls above. Keep it out of Git. Start MediaMTX with `mediamtx <config>`
   and bind RTSP and metrics to loopback. Test denial of an unassigned publisher
   and denial of RTSP access from the site network before using production data.
3. On the site host set `SITE_CAMERA_RTSP_FILE`, `SITE_PUBLISHER_PASSWORD_FILE`,
   `SITE_SRT_PASSPHRASE_FILE`, `SITE_SRT_HOST`, `SITE_SRT_PORT`,
   `SITE_STREAM_PATH` and `SITE_PUBLISHER_USER` using protected provisioning.
   Start `python -m media_gateway.site_publisher` under the isolated account.
   Confirm the publisher process initiates only the provisioned camera session
   and outbound central SRT session.
4. On the central host set `MEDIA_RTSP_HOST`, `MEDIA_RTSP_PORT`, `MEDIA_RTSP_USER`,
   `MEDIA_RTSP_PASSWORD_FILE`, `MEDIA_GATEWAY_TOKEN_FILE` and `MEDIA_BINDINGS_FILE`.
   The bindings JSON maps each camera UUID to an object with `stream_ref` and
   `path`. Start `python -m uvicorn media_gateway.preview_service:from_environment
   --factory --host 127.0.0.1 --port 9081` from `backend-v2` using the media
   requirements. Set FastAPI's `MEDIA_GATEWAY_ORIGIN=http://127.0.0.1:9081` and
   point its `MEDIA_GATEWAY_TOKEN_FILE` to the same protected service credential.
5. Use the existing same-origin HTTPS dashboard. Verify authorized and revoked
   sessions, disabled cameras, cross-organization denial, stream cutoff and
   recovery, ingest metrics, and host monitoring. Hook the network adapter to the
   approved ADR-009 gateway/inference runtime only after verifying its exact
   camera bindings and separate credentials in staging.

## Rollback

Stop the site publisher and revoke its path grant and encryption key. Terminate
active ingress sessions for the revoked path. Disable the business media origin
and stop the private preview service. Dashboard camera and incident configuration
continues to use the existing API. Preserve assignment and incident records.
