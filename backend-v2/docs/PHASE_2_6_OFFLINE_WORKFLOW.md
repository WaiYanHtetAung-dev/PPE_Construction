# Phase 2.6-B offline export and real-model parity

## Stop conditions

Approve checkpoint and dataset rights separately from toolchain execution.
Supply a reviewed approval record, two approved local OCI image digests, both
hash-locked wheel sets, and the de-identified corpus before running the
checkpoint. Missing dependencies, images, rights or fixture approval stop the
corresponding run. A container reduces exposure, while untrusted checkpoint
conversion should run on a dedicated disposable, offline host or VM.

The inspected original Finalboss digest is
`89e96c1da3c6a413a2d4d5d7ad1a06f485355a5096ea155e3b6d260ed9d3b7dd`.
Static metadata reports training on YOLO11m with Ultralytics 8.4.102. V1 pins
8.4.96. Neither version has been selected for release.

## Approved exporter inputs

Copy `infra/onnx_export/toolchains.example.json` outside Git. Each entry
needs the approved `name@sha256:digest`, SHA-256 of its exact
`requirements.lock`, and the approval record ID. The lock must pin
Ultralytics to the selected profile and the agreed CPU PyTorch, ONNX, OpenCV,
NumPy and transitive wheel versions with hashes. Provision each image using
the exporter Dockerfile, a preloaded digest-pinned base, a separate approved
wheelhouse context and no network. The Dockerfile installs with `--no-index
--require-hashes`. Never place credentials or model bytes in the build
context. Preload and verify both final image digests on the offline host.

```sh
python infra/onnx_export/run_offline.py "$CHECKPOINT" "$REVIEW_ROOT/export-102" \
  --toolchains "$REVIEW_ROOT/toolchains.json" --version 8.4.102
python infra/onnx_export/run_offline.py "$CHECKPOINT" "$REVIEW_ROOT/export-96" \
  --toolchains "$REVIEW_ROOT/toolchains.json" --version 8.4.96
python -m infra.onnx_export.compare_exports "$REVIEW_ROOT/export-102" "$REVIEW_ROOT/export-96"
```

The launcher inspects the local image, forbids pulls/network, uses a non-root
UID, limits CPU/RAM/PIDs/artifact size, mounts the original read-only and
writes to a new external directory. The in-container runner checks the wheel
lock digest and installed Ultralytics version before deserialization and
copies the exact checkpoint to private scratch. Export reports retain
checkpoint and output digests, image and lock, installed versions, class
table, FP32 graph shape, opset, preprocessing and NMS settings. Independently
check both output graphs and digests in the disposable offline review environment. A structural pass proves neither
runtime parity nor selection of an exporter.

## Corpus and captures

Copy `infra/onnx_export/corpus.example.json` outside Git. Replace every
placeholder with its actual corpus approval, per-image usage authorization,
SHA-256, dimensions and reduced aspect ratio. Confirm de-identification out of
band. The corpus directory is dedicated and contains only approved image files
named in the manifest. Include square and non-square frames, an empty scene,
multiple people and overlapping PPE. The launcher never mounts the corpus
during export. It permits the corpus only in the 8.4.96 reference run.

```sh
python infra/onnx_export/run_offline.py "$CHECKPOINT" "$REVIEW_ROOT/v1-reference" \
  --toolchains "$REVIEW_ROOT/toolchains.json" --version 8.4.96 --mode reference \
  --corpus-manifest "$REVIEW_ROOT/corpus.json" --corpus-root "$REVIEW_ROOT/frames"
```

The reference captures V1-style BGR decoding and raw post-NMS detections
using both the deployed predictor defaults and explicit square letterbox
with IoU 0.70. Confidence 0.35 and input size 640 match the V1 detector defaults.
Use the actual deployment overrides if they differ and record that change
before collecting results. The reports record effective `rect`, IoU, score
threshold, maximum detection count, corpus fingerprint and sample dimensions.
V1 rectangular padding and the fixed-square ONNX candidate may diverge on
non-square frames. Report the divergence rather than changing tolerances.

For each independently reviewed export, provision the **disposable** verifier
and worker with a signed candidate under a distinct model version. Mount the
approved corpus as the worker's `frames/` namespace. Run capture in the
isolated test network with the two disposable service tokens. The capture
uses read-only eligibility to confirm the candidate digest and evidence
generation before and throughout the run. Inference goes through the existing
authenticated worker; direct model loading is not part of this capture.

```sh
python -m infra.onnx_export.capture_worker "$REVIEW_ROOT/corpus.json" "$REVIEW_ROOT/frames" \
  "$REVIEW_ROOT/onnx-102.json" --origin http://inference-worker:8080 \
  --authority-origin http://eligibility-authority:8081 --token-file "$INGRESS_TOKEN_FILE" \
  --authority-token-file "$ELIGIBILITY_TOKEN_FILE" --model-key finalboss --model-version <signed-version> \
  --export-report "$REVIEW_ROOT/export-102/export.json" --worker-approval <test-run-approval>
python infra/onnx_export/compare_parity.py "$REVIEW_ROOT/v1-reference/v1-default.json" \
  "$REVIEW_ROOT/onnx-102.json" --fixed-square "$REVIEW_ROOT/v1-reference/fixed-square.json"
```

Repeat capture and comparison for 8.4.96. Compare both reference modes
against each signed worker run. A pass requires same-class one-to-one IoU
at least 0.95, absolute score delta at most 0.02, no unmatched detections
at score 0.37 or above and empty responses for the declared empty fixtures.
Report unmatched 0.35 to below 0.37 detections separately. These are the
unchanged Phase 2.6 gates. Reviewer selection requires export, graph and
real-worker evidence, with representative per-aspect-ratio error review.
Names are matched against the fixed eight-class registry profile. Overlap
and suppression behavior are assessed on retained boxes and the existing
synthetic raw-ONNX NMS test.

## Independent status

| Gate | Status |
| --- | --- |
| Workflow implementation | Complete. Validated with synthetic inputs. |
| Export compatibility (8.4.102 / 8.4.96) | NOT TESTED. Approved image digests and wheel locks were not supplied. |
| Real-model parity | NOT TESTED. No approved export or approved de-identified corpus was supplied. |
| Licensing | Pending written clearance for checkpoint, dependencies and fixture use. |
| Human review | Pending. PR #1 remains Draft. |
| Production deployment | No approval or deployment. |
