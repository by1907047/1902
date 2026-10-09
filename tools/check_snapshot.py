"""Verify source identity against the frozen baseline; never touches devices or networks.

Two separate claims are checked:

* Baseline provenance. docs/source-snapshot.json lists the files exported from
  the archived hardware-tested candidate at tag v0.1.0-alpha.1. Its SHA256 is
  pinned below, so the list cannot be edited to match changed source. When the
  tag is available (always in CI), every record is also checked against the
  file contents at that tag.
* Current-source integrity. docs/source-current.json lists every tracked file
  in the baseline scope that changed, was added or was removed after the
  baseline. Unlisted files must still be byte-identical to the baseline. These
  records only describe the current unreleased source delta. Native and
  hardware qualification is revision-specific and documented separately
  in docs/OUT-PIPE-RECOVERY.md.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT/'docs/source-snapshot.json'
CURRENT = ROOT/'docs/source-current.json'
SCOPE = ('NCM-Driver-for-Windows', 'tests')
BASELINE_TAG = 'v0.1.0-alpha.1'
BASELINE_CANDIDATE = 'd522ef2-dirty-469555eaf6648073'
BASELINE_MANIFEST_SHA256 = 'bdc2c2ce874cc5e8fb5a66067f2a1e421fa916a327c36daba458f5e939159221'


def checked_path(text):
    relative = Path(text)
    if (relative.is_absolute() or '..' in relative.parts or
            not relative.parts or relative.parts[0] not in SCOPE):
        raise ValueError('Invalid snapshot path: ' + text)
    return text


def digest(data):
    return len(data), hashlib.sha256(data).hexdigest()


def matches(path, record):
    file = ROOT/path
    if not file.is_file() or file.is_symlink():
        return False
    return digest(file.read_bytes()) == (record['Bytes'], record['SHA256'].lower())


def git(*args, data=None):
    return subprocess.run(['git', *args], cwd=ROOT, input=data, capture_output=True)


def tracked_in_scope():
    """Tracked files in scope, or None outside a git checkout."""
    result = git('ls-files', '-z', '--', *SCOPE)
    if result.returncode != 0:
        return None
    return {p for p in result.stdout.decode('utf-8').split('\0') if p}


def tag_contents(paths):
    """Contents of each path at the baseline tag, or None if the tag is absent."""
    if git('rev-parse', '-q', '--verify', f'refs/tags/{BASELINE_TAG}').returncode != 0:
        return None
    request = ''.join(f'{BASELINE_TAG}:{p}\n' for p in paths).encode('utf-8')
    output = git('cat-file', '--batch', data=request)
    if output.returncode != 0:
        raise SystemExit('git cat-file failed reading ' + BASELINE_TAG)
    out, cursor, contents = output.stdout, 0, {}
    for path in paths:
        end = out.index(b'\n', cursor)
        header = out[cursor:end].split()
        if len(header) != 3 or header[1] != b'blob':
            raise SystemExit(f'{path} is missing at {BASELINE_TAG}')
        size = int(header[2])
        contents[path] = out[end+1:end+1+size]
        cursor = end + 1 + size + 1
    return contents


def main():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_MANIFEST_SHA256:
        raise SystemExit('Baseline manifest changed: docs/source-snapshot.json must stay '
                         f'identical to {BASELINE_TAG}; record later changes in '
                         'docs/source-current.json')
    baseline_manifest = json.loads(raw)
    if baseline_manifest['candidate'] != BASELINE_CANDIDATE:
        raise SystemExit('Unexpected baseline candidate identity')
    baseline = {}
    for entry in baseline_manifest['files']:
        path = checked_path(entry['Path'])
        if path in baseline:
            raise ValueError('Duplicate snapshot path: ' + path)
        baseline[path] = entry

    contents = tag_contents(sorted(baseline))
    if contents is None:
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            raise SystemExit(f'Tag {BASELINE_TAG} is required in CI (checkout fetch-depth: 0)')
        tag_note = f'tag {BASELINE_TAG} unavailable, records not compared with it'
    else:
        stale = [p for p, data in contents.items()
                 if digest(data) != (baseline[p]['Bytes'], baseline[p]['SHA256'].lower())]
        if stale:
            raise SystemExit(f'Baseline records differ from {BASELINE_TAG}: ' + ', '.join(stale))
        tag_note = f'all records match tag {BASELINE_TAG}'

    current = json.loads(CURRENT.read_text())
    reference = current['baseline']
    if (reference['tag'], reference['candidate'], reference['manifest_sha256']) != (
            BASELINE_TAG, BASELINE_CANDIDATE, BASELINE_MANIFEST_SHA256):
        raise SystemExit('docs/source-current.json names a different baseline')
    changed = {checked_path(e['Path']): e for e in current['changed_from_baseline']}
    added = {checked_path(e['Path']): e for e in current['added_after_baseline']}
    removed = {checked_path(p) for p in current['removed_after_baseline']}
    failures = []
    for path in set(changed) | removed:
        if path not in baseline:
            failures.append(path + ' (not in baseline)')
    for path in added:
        if path in baseline:
            failures.append(path + ' (listed as added but in baseline)')

    preserved = 0
    for path, record in baseline.items():
        if path in removed:
            if (ROOT/path).exists():
                failures.append(path + ' (listed as removed but present)')
        elif path in changed:
            if matches(path, record):
                failures.append(path + ' (listed as changed but identical to baseline)')
            elif not matches(path, changed[path]):
                failures.append(path + ' (current record mismatch)')
        elif matches(path, record):
            preserved += 1
        else:
            failures.append(path + ' (differs from baseline but not listed as changed)')
    for path, record in added.items():
        if not matches(path, record):
            failures.append(path + ' (current record mismatch)')

    tracked = tracked_in_scope()
    if tracked is None:
        coverage_note = 'not a git checkout, unlisted files not detected'
    else:
        expected = (set(baseline) - removed) | set(added)
        failures += [p + ' (tracked but not recorded)' for p in sorted(tracked - expected)]
        failures += [p + ' (recorded but not tracked)' for p in sorted(expected - tracked)]
        coverage_note = f'all {len(tracked)} tracked files in scope accounted for'

    if failures:
        raise SystemExit('Source identity mismatch (run tools/update_source_current.py '
                         'only for intended changes):\n  ' + '\n  '.join(sorted(failures)))
    print(f'Baseline {BASELINE_TAG} ({BASELINE_CANDIDATE}): {len(baseline)} archived '
          f'records, manifest hash pinned, {tag_note}', flush=True)
    print(f'Current source: {preserved} files byte-preserved from baseline; '
          f'{len(changed)} changed, {len(added)} added, {len(removed)} removed after it '
          f'({current["status"]}); {coverage_note}', flush=True)


if __name__ == '__main__':
    main()
