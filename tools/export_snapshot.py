"""Mechanically derive a public checksum list from the archived freeze manifest.

Maintainer-only packaging helper. It exports selected file identities, not logs,
machine state or private metadata. Pass the original manifest as an argument.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    'NCM-Driver-for-Windows/.gitmodules',
    'NCM-Driver-for-Windows/scripts/create-and-sign.ps1',
    'NCM-Driver-for-Windows/scripts/install-driver.ps1',
    'NCM-Driver-for-Windows/scripts/rebuild-driver.ps1',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive_manifest', type=Path)
    args = parser.parse_args()
    entries = json.loads(args.archive_manifest.read_text(encoding='utf-8-sig'))
    exported = []
    for entry in entries:
        relative = Path(entry['Path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe archive path')
        if (not relative.parts or relative.parts[0] not in
                ('NCM-Driver-for-Windows', 'tests') or str(relative) in EXCLUDED):
            continue
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing export file: ' + str(relative))
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != entry['Bytes'] or digest != entry['SHA256'].lower():
            raise ValueError('Modified archive file: ' + str(relative))
        exported.append({'Path': str(relative), 'Bytes': len(data), 'SHA256': digest})
    if not exported:
        raise ValueError('Empty export')
    snapshot = {
        'schema': 1,
        'candidate': 'd522ef2-dirty-469555eaf6648073',
        'internal_base_commit': 'd522ef239f613747155dc4a30db55447e6de5e59',
        'original_archive_sha256':
            'd506a9cc587f4dac4ebc2d3b5e3b670064ea6f450c375450fbe531faa7c85b2f',
        'files': exported,
    }
    (ROOT / 'docs/source-snapshot.json').write_text(
        json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
    print(f'Exported {len(exported)} archived file identities')


if __name__ == '__main__':
    main()
