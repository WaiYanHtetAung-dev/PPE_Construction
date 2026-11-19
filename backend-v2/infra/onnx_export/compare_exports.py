"""Compare candidate export evidence without loading checkpoint code."""

import argparse
import hashlib
import json
from pathlib import Path

from inference_worker.onnx_cpu import validate_graph
from infra.onnx_export.corpus import SHA256
from infra.onnx_export.run_offline import EXPECTED


def examine(root: Path, expected_version: str):
    manifest = root / 'export.json'
    artifact = root / 'finalboss.onnx'
    if not manifest.is_file() or not artifact.is_file():
        return {'status': 'NOT TESTED', 'reason': 'Export or artifact unavailable'}
    report = json.loads(manifest.read_text(encoding='utf-8'))
    if (report['versions']['ultralytics'] != expected_version
            or not SHA256.fullmatch(report['lock_sha256']) or report['source_sha256'] != EXPECTED
            or report['input_output_shapes'] != [[[1, 3, 640, 640]], [[1, 12, 8400]]]):
        raise ValueError('Export evidence does not match selected toolchain')
    with artifact.open('rb') as source:
        data = source.read(256 * 1024**2 + 1)
    digest = hashlib.sha256(data).hexdigest()
    if digest != report['artifact_sha256'] or len(data) != report['artifact_bytes']:
        raise ValueError('Export artifact digest or size differs from the report')
    ports = validate_graph(data)
    return {'status': 'PASS', 'artifact_sha256': digest, 'image': report['exporter_image'],
            'lock_sha256': report['lock_sha256'], 'source_sha256': report['source_sha256'],
            'versions': report['versions'], 'shapes': report['input_output_shapes'], 'ports': ports,
            'preprocessing': report['preprocessing'], 'nms': report['nms'],
            'runtime': 'Requires separately signed worker inference and parity evidence'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint_version_export', type=Path, help='8.4.102 output directory')
    parser.add_argument('v1_version_export', type=Path, help='8.4.96 output directory')
    args = parser.parse_args()
    reports = {version: examine(path, version) for version, path in (
        ('8.4.102', args.checkpoint_version_export), ('8.4.96', args.v1_version_export),
    )}
    print(json.dumps(reports, indent=2))
    raise SystemExit(0 if all(r['status'] == 'PASS' for r in reports.values()) else 1)


if __name__ == '__main__':
    main()
