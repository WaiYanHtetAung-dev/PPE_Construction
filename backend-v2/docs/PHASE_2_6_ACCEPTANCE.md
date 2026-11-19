# Phase 2.6 CPU ONNX adapter acceptance

## Profile and controlled export

The candidate accepts self-contained, static, raw YOLO11 detection ONNX bytes.
The profile is FP32 `[1,3,640,640]` with one `[1,12,8400]` output and opset
17. Export parameters disable dynamic shapes, FP16, simplification and embedded
NMS. The CPU worker independently validates metadata, all eight class IDs,
shape, standard operators and inline tensor data before it constructs ORT.
Inference uses RGB bilinear 640-square letterbox, padding 114, FP32 /255,
class-aware IoU 0.70 NMS and at most 300 detections. These are candidate settings
until checked against the exact deployed V1 predictor. Do not silently equate
fixed square padding or Pillow decoding with V1 rectangular padding and OpenCV.

The launcher requires rights/toolchain approval and an approved local image
digest. Prepare the image from a pinned Linux Python base and approved
CPU-only wheelhouse. Use the exporter Dockerfile with an external directory
containing `requirements.lock` with hashes and `wheels/`, and build with no
network. The checkpoint metadata specifies Ultralytics 8.4.102. V1 pins 8.4.96.
A matching exporter and the exact V1 reference runtime both require a separate
compatibility check.

```sh
docker build --pull=false --network=none --build-arg EXPORT_BASE=<approved-base@sha256:digest> \
  -f infra/onnx_export/Dockerfile -t <local-exporter-tag> <approved-wheelhouse-directory>
python infra/onnx_export/run_offline.py <path-to-original-finalboss.pt> <new-external-output> \
  --image <approved-exporter@sha256:digest> --approval <approved-record-id>
```

Make the reviewed image available under the supplied immutable digest before
running the launcher. The sandbox receives only the read-only checkpoint and
conversion script, a private scratch filesystem and a new output directory.
No GPU, network, production secrets or release signer enter the sandbox.
Treat its outputs as untrusted candidates. Validate profile, digest and parity
independently before approving and signing the release. Store weights and real
fixtures only in approved external storage.

## Worker and parity

Set `INFERENCE_DEV_IMAGE_TARGET=cpu` and
`INFERENCE_DEV_RUNTIME_FACTORY=inference_worker.onnx_cpu:factory` for the
opt-in Compose worker. No model paths are passed to ORT. The adapter receives
immutable bytes from the existing worker boundary and releases the session on
context exit. Requests still require live eligibility before loading and
dispatch. The business API and published response schemas are unchanged.

For the real test, independently collect raw V1 and V2 detections on an
approved de-identified corpus. Include an empty scene, multiple people,
overlapping same-class helmets and cross-class equipment, non-square frames and
an invalid image. Check actual V1 defaults first. Compare both the deployed V1
configuration and an explicitly square FP32 V1 reference with the same
confidence and NMS thresholds. Collect JSON keyed by sample ID, with each item
containing `class_id`, `score` and `bbox_xyxy`. Convert v1 worker labels to the
approved raw class IDs for this comparison only. Use `compare_parity.py` with
reference and candidate JSON outside Git.

Predeclared tolerance at confidence 0.35 is one-to-one same-class IoU at least
0.95 and absolute confidence delta at most 0.02. No unmatched detection at
score 0.37 or above. Report unmatched 0.35 to below 0.37 detections separately.
V1-empty fixtures must remain empty. Record both configurations and review all
NMS or preprocessing differences. These checks assess detection parity, while
accuracy needs labeled evaluation data and its own acceptance criteria.

## Evidence

| Gate | Status |
| --- | --- |
| CPU execution and detection transforms | Synthetic ONNX graph executed on actual CPUExecutionProvider. Class mapping, original-frame coordinates, duplicate suppression, cross-class overlap, two person detections, empty output and corrupt-image handling have automated coverage. |
| Worker security with CPU adapter | Automated signed-path tests cover bad signature, digest mismatch, stale and revoked leases, authority disconnect during load, artifact replacement and model identity mismatch. Session release is asserted. |
| Finalboss export / exporter compatibility | Blocked. Approved digest-pinned exporter image and locked wheelhouse were not available for the checkpoint. No checkpoint deserialization was performed. |
| Finalboss license and fixtures | Blocked. Rights clearance and an approved de-identified corpus were not supplied. No real-model smoke, V1 parity or Finalboss CPU performance result is available. |
| CPU baseline | See development log for the small synthetic graph measurement. This does not predict Finalboss or GPU/network capacity. |
| Approval | Draft PR #1. Human approval, production adapter validation and deployment sign-off are pending. |

[Ultralytics licensing](https://www.ultralytics.com/license) and
[PyTorch serialization guidance](https://docs.pytorch.org/docs/stable/notes/serialization.html)
apply to the review. Preserve the previous deployment and database schema
during rollback. Phase 3 and production rollout remain outside this slice.
