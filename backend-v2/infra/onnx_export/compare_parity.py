"""Compare approved raw detections, independently produced by V1 and the ONNX worker."""

import argparse
import json
import math
from pathlib import Path

MATCH_IOU = 0.95
SCORE_DELTA = 0.02
BORDERLINE_HIGH = 0.37


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return intersection / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection)


def load(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not data:
        raise ValueError('Expected a nonempty sample ID mapping')
    for rows in data.values():
        for row in rows:
            score, box, class_id = row['score'], row['bbox_xyxy'], row['class_id']
            if (type(class_id) is not int or not 0 <= class_id <= 7 or not 0.35 <= score <= 1
                    or len(box) != 4 or not all(map(math.isfinite, box))
                    or not 0 <= box[0] < box[2] <= 16384 or not 0 <= box[1] < box[3] <= 16384):
                raise ValueError('Invalid raw detection')
    return data


def compare(reference, candidate):
    if set(reference) != set(candidate):
        raise ValueError('Sample sets differ')
    if not any(reference.values()) or all(reference.values()):
        raise ValueError('Reference corpus needs positive and empty fixtures')
    records = {}
    for sample, expected in sorted(reference.items()):
        actual = candidate[sample]
        remaining = set(range(len(actual)))
        pairs, misses, borderline = [], [], []
        for label in sorted(expected, key=lambda row: -row['score']):
            ranked = [(iou(label['bbox_xyxy'], actual[i]['bbox_xyxy']), i) for i in remaining
                      if actual[i]['class_id'] == label['class_id']]
            overlap, index = max(ranked, default=(0, -1), key=lambda pair: (pair[0], -pair[1]))
            if overlap >= MATCH_IOU:
                remaining.remove(index)
                delta = abs(label['score'] - actual[index]['score'])
                pairs.append({'iou': overlap, 'score_delta': delta})
                if delta > SCORE_DELTA:
                    misses.append('score delta exceeds tolerance')
            elif label['score'] >= BORDERLINE_HIGH:
                misses.append('unmatched V1 detection')
            else:
                borderline.append('unmatched borderline V1 detection')
        for index in sorted(remaining):
            if actual[index]['score'] >= BORDERLINE_HIGH:
                misses.append('unmatched ONNX detection')
            else:
                borderline.append('unmatched borderline ONNX detection')
        if not expected and actual:
            misses.append('V1-empty fixture was not empty')
        records[sample] = {'matched': pairs, 'failures': misses, 'borderline': borderline}
    return {'passed': not any(row['failures'] for row in records.values()), 'samples': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('v1', type=Path)
    parser.add_argument('onnx', type=Path)
    args = parser.parse_args()
    result = compare(load(args.v1), load(args.onnx))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
