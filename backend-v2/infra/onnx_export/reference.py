"""Offline PyTorch reference capture. Imported only inside the exporter sandbox."""

import json
from pathlib import Path

from corpus import load_corpus, read_sample


def capture(model, output_dir):
    import cv2
    import numpy as np

    root = Path('/corpus')
    corpus, corpus_digest = load_corpus('/corpus.json', root)
    results = {'v1-default': {}, 'fixed-square': {}}
    settings = dict(device='cpu', imgsz=640, conf=0.35, verbose=False)
    actual_options = {}
    for sample in corpus['samples']:
        data = read_sample(root, sample)
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (sample['height'], sample['width']):
            raise ValueError('Decoded reference frame does not match corpus dimensions')
        for mode in results:
            kwargs = {} if mode == 'v1-default' else {'rect': False, 'iou': 0.70, 'max_det': 300}
            # Separate predictors prevent sticky overrides from the preceding mode.
            model.predictor = None
            result, = model.predict(source=image, **settings, **kwargs)
            pred = model.predictor.args
            actual_options[mode] = {name: getattr(pred, name) for name in ('rect', 'iou', 'conf', 'imgsz', 'max_det')}
            results[mode][sample['id']] = [
                {'class_id': int(box.cls.item()), 'score': float(box.conf.item()),
                 'bbox_xyxy': box.xyxy[0].tolist()} for box in result.boxes
            ]
    for mode, detections in results.items():
        with (output_dir / f'{mode}.json').open('x', encoding='utf-8') as dest:
            json.dump({'corpus_sha256': corpus_digest, 'mode': mode,
                       'predictor_options': actual_options[mode],
                       'samples': {row['id']: {'purpose': row['purpose'], 'aspect_ratio': row['aspect_ratio'],
                                                  'width': row['width'], 'height': row['height']}
                                   for row in corpus['samples']}, 'detections': detections}, dest, indent=2)
            dest.write('\n')
