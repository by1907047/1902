"""Regenerate docs/source-current.json: the post-baseline source delta.

The baseline (docs/source-snapshot.json, tag v0.1.0-alpha.1) is immutable.
This records every tracked file under the baseline scope that differs from,
was added after, or was removed since that baseline. Run it after changing a
file in scope; tools/check_snapshot.py verifies the result.
"""
import hashlib
import json
from pathlib import Path

from check_snapshot import (BASELINE_CANDIDATE, BASELINE_MANIFEST_SHA256,
                            BASELINE_TAG, CURRENT, MANIFEST, ROOT, SCOPE,
                            tracked_in_scope)


def main():
    baseline = {e['Path']: e for e in json.loads(MANIFEST.read_text())['files']}
    tracked = tracked_in_scope()
    if tracked is None:
        raise SystemExit('A git checkout is required to enumerate tracked files')
    changed, added = [], []
    for path in sorted(tracked):
        data = (ROOT/path).read_bytes()
        record = {'Path': path, 'Bytes': len(data),
                  'SHA256': hashlib.sha256(data).hexdigest()}
        base = baseline.get(path)
        if base is None:
            added.append(record)
        elif (base['Bytes'], base['SHA256'].lower()) != (record['Bytes'], record['SHA256']):
            changed.append(record)
    removed = sorted(set(baseline) - tracked)
    current = {
        'schema': 1,
        'status': 'unreleased: not built with the WDK and not hardware-tested',
        'baseline': {
            'tag': BASELINE_TAG,
            'candidate': BASELINE_CANDIDATE,
            'manifest': str(MANIFEST.relative_to(ROOT)),
            'manifest_sha256': BASELINE_MANIFEST_SHA256,
        },
        'scope': list(SCOPE),
        'changed_from_baseline': changed,
        'added_after_baseline': added,
        'removed_after_baseline': removed,
    }
    CURRENT.write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
    print(f'{len(changed)} changed, {len(added)} added, {len(removed)} removed since {BASELINE_TAG}')


if __name__ == '__main__':
    main()
