"""Run only inside the approved offline conversion sandbox."""

import hashlib
import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

LABELS = ['black helmet', 'blue helmet', 'green helmet', 'person',
          'red helmet', 'vest', 'white helmet', 'yellow helmet']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    source_hash, approval, image, expected_version, lock, mode = sys.argv[1:]
    if expected_version not in ('8.4.102', '8.4.96') or version('ultralytics') != expected_version:
        raise RuntimeError('Exporter must match the approved toolchain profile')
    if digest(Path('/build/requirements.lock')) != lock:
        raise RuntimeError('Exporter wheel lock does not match the approved digest')
    source, local = Path('/input/finalboss.pt'), Path('/tmp/finalboss.pt')
    shutil.copyfile(source, local)
    if digest(local) != source_hash:
        raise RuntimeError('Unexpected checkpoint digest')

    import onnx
    from ultralytics import YOLO

    model = YOLO(str(local), task='detect')
    if model.task != 'detect' or [model.names[i] for i in sorted(model.names)] != LABELS or set(model.names) != set(range(8)):
        raise RuntimeError('Checkpoint task or labels incompatible')
    if mode == 'reference':
        if expected_version != '8.4.96':
            raise RuntimeError('Reference must use the V1-pinned toolchain')
        from reference import capture
        capture(model, Path('/output'))
        with Path('/output/reference-toolchain.json').open('x', encoding='utf-8') as stream:
            json.dump({'approval': approval, 'image': image, 'lock_sha256': lock,
                       'source_sha256': source_hash, 'ultralytics': expected_version,
                       'torch': version('torch'), 'opencv': __import__('cv2').__version__}, stream, indent=2)
        return
    if mode != 'export':
        raise RuntimeError('Unsupported offline mode')
    options = dict(format='onnx', opset=17, imgsz=640, batch=1, dynamic=False,
                   half=False, simplify=False, nms=False, device='cpu')
    output = Path(model.export(**options))
    graph = onnx.load(output, load_external_data=False)
    onnx.helper.set_model_props(graph, {
        'ppe.profile': 'finalboss-yolo11-raw-v1', 'ppe.labels': json.dumps(LABELS),
    })
    onnx.checker.check_model(graph)
    shapes = []
    for items in (graph.graph.input, graph.graph.output):
        shapes.append([[d.dim_value for d in item.type.tensor_type.shape.dim] for item in items])
    if shapes != [[[1, 3, 640, 640]], [[1, 12, 8400]]]:
        raise RuntimeError('Exporter did not produce the approved static detector profile')
    target = Path('/output/finalboss.onnx')
    with target.open('xb') as stream:
        stream.write(graph.SerializeToString())
    record = {
        'approval': approval, 'exporter_image': image, 'source_sha256': source_hash,
        'lock_sha256': lock,
        'artifact_sha256': digest(target), 'artifact_bytes': target.stat().st_size,
        'versions': {name: version(name) for name in ('ultralytics', 'torch', 'onnx')},
        'metadata': {'task': model.task, 'labels': LABELS},
        'export_options': options, 'input_output_shapes': shapes,
        'preprocessing': 'RGB FP32 NCHW /255, bilinear 640x640 letterbox with 114 padding',
        'nms': {'embedded': False, 'class_aware_iou': 0.7, 'max_detections': 300},
        'status': 'candidate; requires independent validation and release signature',
    }
    with Path('/output/export.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
