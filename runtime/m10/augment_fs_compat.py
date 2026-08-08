#!/usr/bin/env python3
"""Compose the locked M10 filesystem, eventfd2, and path bridges.

All three augmenter implementations are materialized in the current
tree.  The target workflow therefore needs no historical Git objects
and remains reproducible under actions/checkout's shallow default.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HRT_M10_FS_SELF_CONTAINED_TRACE_V3 = True


def run_module(path: Path, argv: list[str]) -> None:
    spec = importlib.util.spec_from_file_location(
        'hrt_composed_' + path.stem, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f'unable to load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = sys.argv
    try:
        sys.argv = [str(path), *argv]
        module.main()
    finally:
        sys.argv = previous


def main() -> int:
    if len(sys.argv) != 3:
        print(f'usage: {sys.argv[0]} INPUT.c OUTPUT.c', file=sys.stderr)
        return 64
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    here = Path(__file__).resolve()
    filesystem = here.with_name('augment_fs_compat_base.py')
    eventfd = here.parents[1] / 'm3' / 'augment_eventfd2.py'
    path_trace = here.with_name('augment_path_trace_base.py')
    for required in (filesystem, eventfd, path_trace):
        if not required.is_file():
            raise SystemExit(f'missing composed augmenter: {required}')

    with tempfile.TemporaryDirectory(prefix='hrt-m10-composed-') as tmp:
        directory = Path(tmp)
        stage1 = directory / 'filesystem.c'
        stage2 = directory / 'eventfd2.c'
        run_module(filesystem, [str(source), str(stage1)])
        first = stage1.read_text(encoding='utf-8')
        if ('case LINUX_SYS_EVENTFD2:' in first and
            'host_eventfd2_bridge' in first):
            shutil.copy2(stage1, stage2)
        else:
            subprocess.run(
                [sys.executable, str(eventfd),
                 str(stage1), str(stage2)], check=True)
        second = stage2.read_text(encoding='utf-8')
        if 'HRT M9 PATH:' in second:
            shutil.copy2(stage2, output)
        else:
            run_module(path_trace, [str(stage2), str(output)])

    final = output.read_text(encoding='utf-8')
    requirements = {
        'case LINUX_SYS_RENAME:': 1,
        'case LINUX_SYS_EVENTFD2:': 1,
        'host_eventfd2_bridge': 2,
        'HRT M9 PATH:': 1,
        'm9_trace_path("open"': 1,
        'm9_trace_path("fstatat"': 1,
    }
    for marker, minimum in requirements.items():
        count = final.count(marker)
        if count < minimum:
            raise SystemExit(
                f'generated marker {marker!r}: expected at least '
                f'{minimum}, found {count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
