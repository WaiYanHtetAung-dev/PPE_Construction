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


def validate_detections(data):
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


def compare_capture(reference, candidate, expected_mode):
    if (reference.get('mode') != expected_mode or candidate.get('mode') != 'verified-worker'
            or not reference.get('corpus_sha256')
            or reference['corpus_sha256'] != candidate.get('corpus_sha256')
            or reference.get('samples') != candidate.get('samples')):
        raise ValueError('Capture modes, corpus digest or declared samples differ')
    expected, actual = map(validate_detections, (reference['detections'], candidate['detections']))
    samples = reference['samples']
    if set(samples) != set(expected):
        raise ValueError('Capture sample list differs from detections')
    result = compare(expected, actual)
    for key, sample in samples.items():
        record = result['samples'][key]
        record.update(sample)
        record['v1_count'], record['onnx_count'] = len(expected[key]), len(actual[key])
        if sample['purpose'] == 'empty' and (expected[key] or actual[key]):
            record['failures'].append('Declared empty fixture produced detections')
        if sample['purpose'] == 'multiple_people':
            for side, rows in (('V1', expected[key]), ('ONNX', actual[key])):
                if sum(item['class_id'] == 3 for item in rows) < 2:
                    record['failures'].append(f'{side} did not detect multiple people')
    result['passed'] = not any(row['failures'] for row in result['samples'].values())
    result['predictor_options'] = reference['predictor_options']
    return result


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('v1', type=Path)
    parser.add_argument('onnx', type=Path)
    parser.add_argument('--fixed-square', type=Path)
    args = parser.parse_args()
    legacy, candidate = load(args.v1), load(args.onnx)
    if args.fixed_square:
        comparisons = {
            'v1-default': compare_capture(legacy, candidate, 'v1-default'),
            'fixed-square': compare_capture(load(args.fixed_square), candidate, 'fixed-square'),
        }
        result = {'passed': all(item['passed'] for item in comparisons.values()),
                  'artifact_sha256': candidate['artifact_sha256'],
                  'corpus_sha256': candidate['corpus_sha256'], 'comparisons': comparisons}
    else:
        if 'detections' in legacy or 'detections' in candidate:
            parser.error('Capture reports require both V1 modes via --fixed-square')
        result = compare(validate_detections(legacy), validate_detections(candidate))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
