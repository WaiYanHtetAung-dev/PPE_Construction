"""Validate an approved external parity corpus without decoding its images."""

import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path

PURPOSES = {'empty', 'multiple_people', 'overlapping_ppe', 'ordinary'}
MAX_FILES = 500
MAX_FRAME_BYTES = 8 * 1024**2
APPROVAL = re.compile(r'[A-Za-z0-9._-]{1,128}')
SHA256 = re.compile(r'[a-f0-9]{64}')


def load_corpus(manifest, root):
    with Path(manifest).open('rb') as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Corpus manifest too large')
    data = json.loads(raw)
    if (set(data) != {'schema_version', 'approval', 'de_identified', 'samples'}
            or data['schema_version'] != '1.0' or data['de_identified'] is not True
            or not APPROVAL.fullmatch(data['approval']) or data['approval'].startswith('REPLACE-')):
        raise ValueError('Invalid corpus approval or schema')
    samples = data['samples']
    if not 1 <= len(samples) <= MAX_FILES:
        raise ValueError('Invalid corpus size')
    ids, names, purposes, shapes = set(), set(), set(), set()
    for row in samples:
        if set(row) != {'id', 'file', 'sha256', 'usage_authorization', 'width', 'height', 'aspect_ratio', 'purpose'}:
            raise ValueError('Unexpected corpus sample fields')
        name, sample_id, purpose = row['file'], row['id'], row['purpose']
        width, height = row['width'], row['height']
        if (not APPROVAL.fullmatch(sample_id) or sample_id in ids or name in names
                or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}\.(?:jpg|jpeg|png)', name)
                or '..' in name or not SHA256.fullmatch(row['sha256'])
                or not APPROVAL.fullmatch(row['usage_authorization'])
                or row['usage_authorization'].startswith('REPLACE-') or purpose not in PURPOSES
                or type(width) is not int or type(height) is not int
                or not 1 <= width <= 16384 or not 1 <= height <= 16384 or width * height > 16 * 1024**2):
            raise ValueError('Invalid corpus sample metadata')
        ratio = Fraction(width, height)
        if row['aspect_ratio'] != f'{ratio.numerator}:{ratio.denominator}':
            raise ValueError('Corpus aspect ratio is inconsistent')
        ids.add(sample_id)
        names.add(name)
        purposes.add(purpose)
        shapes.add(width == height)
        read_sample(root, row)
    if shapes != {False, True} or not {'empty', 'multiple_people', 'overlapping_ppe'} <= purposes:
        raise ValueError('Corpus must cover square, non-square, empty, multiple-person and overlapping-PPE inputs')
    return data, hashlib.sha256(raw).hexdigest()


def read_sample(root, sample):
    path = Path(root) / sample['file']
    if path.is_symlink() or not path.is_file():
        raise ValueError('Corpus image must be a regular file')
    with path.open('rb') as stream:
        data = stream.read(MAX_FRAME_BYTES + 1)
    if not 0 < len(data) <= MAX_FRAME_BYTES or hashlib.sha256(data).hexdigest() != sample['sha256']:
        raise ValueError('Corpus image size or digest mismatch')
    return data


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    corpus, digest = load_corpus(args.manifest, args.root)
    print(json.dumps({'corpus_sha256': digest, 'samples': len(corpus['samples'])}))
