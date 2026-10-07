"""Run bounded local regression fixtures, not a Windows build or hardware test."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    subprocess.run(command, cwd=ROOT, env=env, check=True, timeout=90)


def main():
    if not shutil.which('clang++'):
        raise SystemExit('clang++ is required for the ASan/UBSan probes')
    py = sys.executable
    run([py, 'tools/check_snapshot.py'])
    run([py, 'tests/source_identity_tests.py'])
    run([py, 'tests/package_tests.py',
         'NCM-Driver-for-Windows/host/SidelineAppleNcm1902.inf'])
    for test in ('build_policy_tests.py', 'lifecycle_policy_tests.py'):
        run([py, 'tests/' + test])
    with tempfile.TemporaryDirectory(prefix='apple1902-validation-') as temp:
        binary = str(Path(temp) / 'validation')
        run(['clang++', '-std=c++17', '-fsanitize=address,undefined', '-g',
             'tests/validation_tests.cpp', '-o', binary])
        run([binary])
    for mode in ('valid16', 'valid32', 'null', 'chain', 'prefixes', 'empty',
                 'cycle', 'skip', 'emptycycle', 'tx', 'malformed'):
        run([py, 'tests/ntb_review_probe.py', mode])
    for probe in ('rx_completion_probe.py', 'rx_ring_probe.py', 'rx_stop_probe.py',
                  'tx_advance_probe.py', 'buffer_creation_probe.py',
                  'adapter_lifecycle_probe.py', 'host_reprepare_probe.py',
                  'host_memory_probe.py', 'ntb_fit_probe.py',
                  'host_diagnostics_probe.py'):
        run([py, 'tests/' + probe])
    print('All portable suites passed; no Windows driver/device was exercised.')


if __name__ == '__main__':
    main()
