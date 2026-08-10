#!/usr/bin/env python3
"""Create a diagnostic replay that fills the exact HOffice product tree.

The credible-editor frontier creates ``hanul::DocumentTabImpl`` but never adds
an ``hword::HwordAppView`` page.  Startup traces show hundreds of missing HOffice
font, resource and shared-data paths.  The curated bootstrap rootfs is a
prepatched ELF shadow root, so blindly extracting the package over it would
replace verified ``syscall``/FS instruction patches with original Linux bytes.

This transform therefore performs a reversible closure-fill experiment:

* enumerate every immutable package entry below ``/opt/hnc/hoffice11``;
* partition the list with ``lexists`` against the mounted shadow root;
* extract only entries that are genuinely absent;
* verify every object in ``.hrt-prepatched-v1`` both before and after filling;
* retain all/missing/existing manifests, counts and product byte totals; and
* apply the existing culture patch and custom QPA afterwards as before.

No existing product entry is overwritten by this experiment.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.source.read_text(encoding="utf-8")
    if "full-product-payload-paths.txt" in text:
        raise SystemExit("full product payload replay is already present")

    anchor = '''    ./opt/hnc/hoffice11/Bin/qt/translations/qt_en.qm \\
    ./opt/hnc/hoffice11/Bin/qt/translations/qt_ko.qm
printf '%s  %s\\n' \\
'''
    replacement = '''    ./opt/hnc/hoffice11/Bin/qt/translations/qt_en.qm \\
    ./opt/hnc/hoffice11/Bin/qt/translations/qt_ko.qm

# M11 diagnostic closure gate: add every product entry missing from the
# prepatched shadow root, but never overwrite an existing patched object.
tar -tf "build/input/deb/$data_member" \\
    | LC_ALL=C grep -E '^\\./opt/hnc/hoffice11(/|$)' \\
    | LC_ALL=C sort -u \\
    >build/proof/full-product-payload-paths.txt
test -s build/proof/full-product-payload-paths.txt
python3 - "$root" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
all_paths = Path('build/proof/full-product-payload-paths.txt')
missing_path = Path('build/proof/full-product-payload-missing-paths.txt')
existing_path = Path('build/proof/full-product-payload-existing-paths.txt')
missing = []
existing = []
for line in all_paths.read_text(encoding='utf-8').splitlines():
    relative = line[2:] if line.startswith('./') else line.lstrip('/')
    target = root / relative
    (existing if os.path.lexists(target) else missing).append(line)
missing_path.write_text(
    ''.join(value + '\n' for value in missing), encoding='utf-8')
existing_path.write_text(
    ''.join(value + '\n' for value in existing), encoding='utf-8')

marker_path = root / '.hrt-prepatched-v1'
marker = json.loads(marker_path.read_text(encoding='utf-8'))
verified = []
for record in marker['objects']:
    target = root / record['path'].lstrip('/')
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != record['sha256_after']:
        raise SystemExit(
            f"prepatched object changed before closure fill: {record['path']} "
            f"{actual} != {record['sha256_after']}")
    verified.append({'path': record['path'], 'sha256': actual})
Path('build/proof/prepatched-object-integrity-before.json').write_text(
    json.dumps({
        'schema': 1,
        'object_count': len(verified),
        'marker_sha256': hashlib.sha256(marker_path.read_bytes()).hexdigest(),
        'objects': verified,
    }, indent=2) + '\n',
    encoding='utf-8')
print(json.dumps({
    'all_entries': len(missing) + len(existing),
    'missing_entries': len(missing),
    'existing_entries': len(existing),
    'prepatched_objects': len(verified),
}, indent=2))
PY

if test -s build/proof/full-product-payload-missing-paths.txt; then
    tar -xf "build/input/deb/$data_member" -C "$root" \\
        -T build/proof/full-product-payload-missing-paths.txt
fi

python3 - "$root" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
marker_path = root / '.hrt-prepatched-v1'
marker = json.loads(marker_path.read_text(encoding='utf-8'))
verified = []
for record in marker['objects']:
    target = root / record['path'].lstrip('/')
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != record['sha256_after']:
        raise SystemExit(
            f"prepatched object overwritten by closure fill: {record['path']} "
            f"{actual} != {record['sha256_after']}")
    verified.append({'path': record['path'], 'sha256': actual})
Path('build/proof/prepatched-object-integrity-after.json').write_text(
    json.dumps({
        'schema': 1,
        'object_count': len(verified),
        'marker_sha256': hashlib.sha256(marker_path.read_bytes()).hexdigest(),
        'objects': verified,
    }, indent=2) + '\n',
    encoding='utf-8')
PY

find "$root/opt/hnc/hoffice11" -type f -print0 \\
    | python3 -c 'import os,sys; data=sys.stdin.buffer.read().split(b"\\0"); paths=[p for p in data if p]; print(sum(os.stat(p).st_size for p in paths))' \\
    >build/proof/full-product-payload-bytes.txt
wc -l <build/proof/full-product-payload-paths.txt \\
    | tr -d ' ' >build/proof/full-product-payload-count.txt
wc -l <build/proof/full-product-payload-missing-paths.txt \\
    | tr -d ' ' >build/proof/full-product-payload-missing-count.txt
wc -l <build/proof/full-product-payload-existing-paths.txt \\
    | tr -d ' ' >build/proof/full-product-payload-existing-count.txt
printf 'HRT M11 PAYLOAD: entries=%s missing=%s existing=%s bytes=%s\\n' \\
    "$(cat build/proof/full-product-payload-count.txt)" \\
    "$(cat build/proof/full-product-payload-missing-count.txt)" \\
    "$(cat build/proof/full-product-payload-existing-count.txt)" \\
    "$(cat build/proof/full-product-payload-bytes.txt)"

printf '%s  %s\\n' \\
'''
    text = replace_once(text, anchor, replacement,
                        "complete product payload insertion")

    required = {
        "full-product-payload-paths.txt": 4,
        "full-product-payload-missing-paths.txt": 4,
        "full-product-payload-existing-paths.txt": 2,
        "full-product-payload-bytes.txt": 2,
        "full-product-payload-count.txt": 2,
        "full-product-payload-missing-count.txt": 2,
        "full-product-payload-existing-count.txt": 2,
        "prepatched-object-integrity-before.json": 1,
        "prepatched-object-integrity-after.json": 1,
        "os.path.lexists": 1,
        "record['sha256_after']": 4,
        "HRT M11 PAYLOAD:": 1,
        "^\\./opt/hnc/hoffice11(/|$)": 1,
        "patch_hword_utility_culture_redirect.py": 1,
        "libqhrtappkit.so.xz": 1,
    }
    for marker, expected in required.items():
        actual = text.count(marker)
        if actual != expected:
            raise SystemExit(
                f"full-payload marker mismatch for {marker!r}: "
                f"expected {expected}, found {actual}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    args.output.chmod(0o755)


if __name__ == "__main__":
    main()
