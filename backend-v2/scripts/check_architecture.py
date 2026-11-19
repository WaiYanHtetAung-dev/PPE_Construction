"""Stop model/media runtime dependencies from sneaking into business backend.

Run: python scripts/check_architecture.py
This is a structural guard, not a complete security scanner.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'torch', 'ultralytics', 'cv2', 'onnxruntime', 'tensorrt', 'av', 'decord', 'gi'}


def find_violations() -> list[str]:
    violations = []
    for path in (ROOT / 'app').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split('.')[0] in FORBIDDEN:
                    violations.append(f'{path.relative_to(ROOT)}:{node.lineno}: forbidden import {name}')
    for artifact in (ROOT / 'app').rglob('*'):
        if artifact.is_file() and artifact.suffix.lower() in {'.pt', '.onnx', '.engine', '.trt'}:
            violations.append(f'{artifact.relative_to(ROOT)}: model artifact in business backend')
    return violations


if __name__ == '__main__':
    found = find_violations()
    if found:
        print('\n'.join(found))
        raise SystemExit(1)
    print('PASS: business API has no forbidden AI/media imports or weights')
