"""Check internal links in Markdown docs, README, AGENTS and agent quickstart."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / 'README.md', ROOT / 'AGENTS.md', ROOT / 'agent.md'] + list((ROOT/'docs').rglob('*.md'))
LINK = re.compile(r'(?<!!)\[[^]]+\]\(([^)]+)\)')
errors = []
for path in FILES:
    if not path.exists():
        errors.append(f'missing {path}')
        continue
    body = path.read_text(encoding='utf-8')
    for match in LINK.finditer(body):
        url = match.group(1).split('#')[0]
        if not url or url.startswith(('http://','https://','mailto:')):
            continue
        if not (path.parent / url).exists():
            errors.append(f'{path.relative_to(ROOT)} -> {url}')
if errors:
    print('Broken documentation links:\n' + '\n'.join(errors))
    raise SystemExit(1)
print(f'PASS: {len(FILES)} Markdown files checked for local link targets')
