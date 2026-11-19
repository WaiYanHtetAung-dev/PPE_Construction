# Phase 2.6-C offline host readiness

## Provision external evidence

Provision a separate Linux amd64 disposable host or VM offline. Transfer the
two reviewed OCI references using their full repo digests and keep both
profiles independent. The profile file is based on
`infra/onnx_export/toolchains.example.json`. Do not use the generic inference
or Python images as exporter images. Prepare each image with a preloaded
digest-pinned Python base and an external platform-specific wheelhouse. Use
the exporter Dockerfile and the separately reviewed `requirements.lock`
containing exact pins and SHA-256 hashes for every direct and transitive wheel.
Use no indexes, remote links, source archives, markers or unreviewed packages.
Store the actual lock digests with the approved image references.

Store reviewed approval files outside Git in an operator-controlled read-only
directory. Each is named `<id>.json` and contains `id`, `status` (approved),
`purpose` and `bindings`. These are references to real authorizations. The
launcher validates the files and bindings. It does not certify their source
or the underlying licensing decision.

| Purpose | Required bindings |
| --- | --- |
| checkpoint-rights | `checkpoint_sha256` |
| exporter-toolchain | `version`, `image` (full OCI reference), `lock_sha256` |
| corpus | `corpus_sha256` (exact manifest bytes) |
| fixture | `image_sha256` |

Use the [corpus template](../infra/onnx_export/corpus.example.json) outside
Git. Fill real usage authorization, de-identification approval, filenames,
SHA-256, dimensions, reduced width:height ratio and purpose. The validator
requires square and non-square samples, a declared empty scene, multiple
people and overlapping PPE. The reference corpus mount must be dedicated;
approval and manifest files are kept alongside it in a separate directory.
Use approved de-identified images only.

## Check both profiles before mounting Finalboss

The commands use shell variables supplied by the reviewer. The target paths
must be new and outside all Git checkouts. A preflight-only run creates no
output directory and never mounts the checkpoint. It checks the source hash
by reading bytes on the host. The container probes the expected local Linux
amd64 image, non-root UID, loopback-only networking, read-only filesystem,
installed pins, lock digest and dependency closure using local binary wheels
and pip hash checking. The real runner repeats preflight before mounting the
checkpoint. An authorization or dependency failure stops the run.

```sh
python infra/onnx_export/corpus.py "$REVIEW_ROOT/corpus.json" "$REVIEW_ROOT/frames"
for VERSION in 8.4.102 8.4.96; do
  python infra/onnx_export/run_offline.py "$CHECKPOINT" "$REVIEW_ROOT/export-$VERSION" \
    --toolchains "$REVIEW_ROOT/toolchains.json" --approval-dir "$REVIEW_ROOT/approvals" \
    --rights-approval "$CHECKPOINT_RIGHTS_APPROVAL" --version "$VERSION" --preflight-only || exit 1
done
python infra/onnx_export/run_offline.py "$CHECKPOINT" "$REVIEW_ROOT/v1-reference" \
  --toolchains "$REVIEW_ROOT/toolchains.json" --approval-dir "$REVIEW_ROOT/approvals" \
  --rights-approval "$CHECKPOINT_RIGHTS_APPROVAL" --version 8.4.96 --mode reference \
  --corpus-manifest "$REVIEW_ROOT/corpus.json" --corpus-root "$REVIEW_ROOT/frames" --preflight-only
```

After rights and both image preflights are approved, repeat the respective
command without `--preflight-only`. The actual run mounts only the reviewed
scripts, read-only checkpoint, any independently approved reference data,
private scratch and fresh output. Do not mount production credentials or a
Docker socket. Quarantine and independently validate the outputs before
signing. Follow [the comparison workflow](PHASE_2_6_OFFLINE_WORKFLOW.md) for
the signed-worker parity captures.

## Audit result

The source digest matches the recorded Finalboss fingerprint.
A checkpoint-free infrastructure probe verified non-root, loopback-only and
read-only Docker constraints. Synthetic tests exercise image digest, lock
structure, approval binding, corpus checks and launch denial. No approved
exporter image/lock/authorization bundle or actual corpus was supplied.
Profile readiness, real export and parity therefore remain not tested.
Do not select a toolchain or request production approval from these results.

[pip hash checking](https://pip.pypa.io/en/stable/topics/secure-installs/) ?
[Docker none network](https://docs.docker.com/engine/network/drivers/none/)
