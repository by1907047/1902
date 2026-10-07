"""Verify the byte-preserved candidate export; never touches devices or networks."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'docs/source-snapshot.json').read_text())
    failures = []
    seen = set()
    for entry in manifest['files']:
        relative = Path(entry['Path'])
        if (relative.is_absolute() or '..' in relative.parts or
                not relative.parts or relative.parts[0] not in
                ('NCM-Driver-for-Windows', 'tests') or str(relative) in seen):
            raise ValueError('Invalid or duplicate snapshot path')
        seen.add(str(relative))
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            failures.append(str(relative))
            continue
        data = path.read_bytes()
        if (len(data) != entry['Bytes'] or
                hashlib.sha256(data).hexdigest() != entry['SHA256'].lower()):
            failures.append(str(relative))
    if failures:
        raise SystemExit('Snapshot mismatch: ' + ', '.join(failures))
    print(f"Snapshot verified: {len(seen)} byte-preserved files", flush=True)


if __name__ == '__main__':
    main()
