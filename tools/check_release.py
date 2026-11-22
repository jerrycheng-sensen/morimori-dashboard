"""Fail before launch/tests if a release snapshot is missing committed app files."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    manifest = json.loads((root / 'release-manifest.json').read_text())
    missing = [p for p in manifest['files'] if not (root / p).is_file()]
    for path in [root / 'app.py', *sorted((root / 'mori').glob('*.py'))]:
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('mori.'):
                module = node.module.replace('.', '/') + '.py'
                if not (root / module).is_file():
                    missing.append(module)
    if missing:
        raise SystemExit('Release is incomplete: ' + ', '.join(sorted(set(missing))))
    print(f'Release complete: {len(manifest["files"])} files; internal imports present.')


if __name__ == '__main__':
    check()
