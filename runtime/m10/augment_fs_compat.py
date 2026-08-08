#!/usr/bin/env python3
"""Compose the locked M10 filesystem bridge with eventfd2 support.

``augment_fs_compat_base.py`` is the exact bridge present when this
wrapper was installed.  It already contains the verified flock,
link, chmod, fstatfs, and atomic rename translations.  This wrapper
runs that implementation first and then applies the independently
proven Linux eventfd2 bridge used by the mature HWord runtime.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HRT_M10_FS_EVENTFD2_WRAPPER_V1 = True


def run_base(source: Path, output: Path) -> None:
    base = Path(__file__).with_name('augment_fs_compat_base.py')
    spec = importlib.util.spec_from_file_location(
        'hrt_m10_fs_compat_base', base)
    if spec is None or spec.loader is None:
        raise SystemExit('unable to load augment_fs_compat_base.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = sys.argv
    try:
        sys.argv = [str(base), str(source), str(output)]
        module.main()
    finally:
        sys.argv = previous


def main() -> int:
    if len(sys.argv) != 3:
        print(f'usage: {sys.argv[0]} INPUT.c OUTPUT.c', file=sys.stderr)
        return 64

    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    eventfd = (Path(__file__).resolve().parents[1] /
               'm3' / 'augment_eventfd2.py')
    if not eventfd.is_file():
        raise SystemExit(f'missing proven eventfd2 augmenter: {eventfd}')

    with tempfile.TemporaryDirectory(prefix='hrt-m10-fs-') as tmp:
        base_output = Path(tmp) / 'fs-base.c'
        run_base(source, base_output)
        text = base_output.read_text(encoding='utf-8')
        if ('case LINUX_SYS_EVENTFD2:' in text and
            'host_eventfd2_bridge' in text):
            shutil.copy2(base_output, output)
        else:
            subprocess.run(
                [sys.executable, str(eventfd),
                 str(base_output), str(output)],
                check=True,
            )

    generated = output.read_text(encoding='utf-8')
    required = {
        'case LINUX_SYS_EVENTFD2:': 1,
        'host_eventfd2_bridge': 2,
        'case LINUX_SYS_RENAME:': 1,
    }
    for marker, minimum in required.items():
        count = generated.count(marker)
        if count < minimum:
            raise SystemExit(
                f'filesystem compatibility marker {marker!r}: '
                f'expected at least {minimum}, found {count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
