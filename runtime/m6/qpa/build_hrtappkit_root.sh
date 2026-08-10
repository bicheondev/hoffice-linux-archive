#!/usr/bin/env bash
set -euo pipefail

: "${PROGRAM:?PROGRAM is required}"
: "${PROGRAM_SHA256:?PROGRAM_SHA256 is required}"
: "${QTBASE_COMMIT:?QTBASE_COMMIT is required}"
: "${QPA_GUEST:?QPA_GUEST is required}"

mkdir -p build/rootfs build/report build/qpa-build build/plugin-root

expected=$(awk '{print $1; exit}' build/input/hword-rootfs.tar.gz.sha256)
actual=$(sha256sum build/input/hword-rootfs.tar.gz | awk '{print $1}')
test "$actual" = "$expected"
tar -xzf build/input/hword-rootfs.tar.gz -C build/rootfs

test -s build/rootfs/.hrt-closure-v1.json
test -s build/rootfs/.hrt-prepatched-v1
test -f "build/rootfs${PROGRAM}"
test -f build/rootfs/opt/hnc/hoffice11/Bin/qt/lib/libQt5Core.so.5
test -f build/rootfs/opt/hnc/hoffice11/Bin/qt/lib/libQt5Gui.so.5

python3 - "$PROGRAM" "$PROGRAM_SHA256" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path('build/rootfs')
guest = sys.argv[1]
marker = json.loads((root / '.hrt-prepatched-v1').read_text())
record, = [item for item in marker['objects'] if item['path'] == guest]
assert record['sha256_before'] == sys.argv[2], record
actual = hashlib.sha256((root / guest.lstrip('/')).read_bytes()).hexdigest()
assert actual == record['sha256_after'], (actual, record)
pathlib.Path('build/report/hword-lock.json').write_text(
    json.dumps(record, indent=2) + '\n')
PY

git init build/qtbase
git -C build/qtbase remote add origin https://github.com/qt/qtbase.git
git -C build/qtbase fetch --depth=1 origin "$QTBASE_COMMIT"
git -C build/qtbase checkout --detach FETCH_HEAD
test "$(git -C build/qtbase rev-parse HEAD)" = "$QTBASE_COMMIT"
test -f build/qtbase/src/plugins/platforms/offscreen/qoffscreenwindow.cpp
printf '%s\n' "$QTBASE_COMMIT" > build/report/qtbase-commit.txt
sha256sum \
  build/qtbase/src/plugins/platforms/offscreen/main.cpp \
  build/qtbase/src/plugins/platforms/offscreen/qoffscreenintegration.cpp \
  build/qtbase/src/plugins/platforms/offscreen/qoffscreenwindow.cpp \
  build/qtbase/src/plugins/platforms/offscreen/qoffscreencommon.cpp \
  > build/report/qt-offscreen-source-sha256.txt

docker run --rm \
  -v "$PWD:/work" -w /work \
  debian:buster-slim bash -lc '
    set -euo pipefail
    cat > /etc/apt/sources.list <<EOF

deb [trusted=yes] http://archive.debian.org/debian buster main
deb [trusted=yes] http://archive.debian.org/debian buster-updates main
deb [trusted=yes] http://archive.debian.org/debian-security buster/updates main
EOF
    printf "Acquire::Check-Valid-Until \"false\";\n" \
      > /etc/apt/apt.conf.d/99archive
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential ca-certificates pkg-config \
      qt5-qmake qtbase5-dev qtbase5-private-dev qtbase5-dev-tools \
      libfontconfig1-dev libfreetype6-dev libx11-dev libxext-dev \
      libgl1-mesa-dev
    qmake -query QT_VERSION | tee /work/build/report/qmake-version.txt
    test "$(qmake -query QT_VERSION)" = 5.11.3
    cd /work/build/qpa-build
    qmake /work/runtime/m6/qpa/hrtappkit.pro \
      QTOFFSCREEN_DIR=/work/build/qtbase/src/plugins/platforms/offscreen
    make -j2 V=1
  '

test -f build/qpa-build/out/libqhrtappkit.so
file build/qpa-build/out/libqhrtappkit.so | tee build/report/qpa-file.txt
readelf -hW build/qpa-build/out/libqhrtappkit.so \
  | tee build/report/qpa-elf-header.txt
readelf -dW build/qpa-build/out/libqhrtappkit.so \
  | tee build/report/qpa-dynamic.txt
readelf -Ws build/qpa-build/out/libqhrtappkit.so \
  | tee build/report/qpa-symbols.txt
strings build/qpa-build/out/libqhrtappkit.so \
  | grep -E 'hrtappkit|HRT M6 QPA' \
  | tee build/report/qpa-markers.txt
grep -F 'Shared object file: [libQt5Gui.so.5]' build/report/qpa-dynamic.txt
grep -F 'Shared object file: [libQt5Core.so.5]' build/report/qpa-dynamic.txt
sha256sum build/qpa-build/out/libqhrtappkit.so \
  > build/report/qpa-unpatched.sha256

mkdir -p "build/plugin-root$(dirname "$QPA_GUEST")"
cp build/qpa-build/out/libqhrtappkit.so "build/plugin-root${QPA_GUEST}"
python3 runtime/m3/prepatch_elf.py build/plugin-root \
  | tee build/report/qpa-prepatch.txt
test -s build/plugin-root/.hrt-prepatched-v1
python3 - "$QPA_GUEST" <<'PY'
import json
import pathlib
import sys

marker = json.loads(
    pathlib.Path('build/plugin-root/.hrt-prepatched-v1').read_text())
guest = sys.argv[1]
record, = [item for item in marker['objects'] if item['path'] == guest]
assert record['syscalls'] >= 1, record
pathlib.Path('build/report/qpa-prepatch-lock.json').write_text(
    json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
PY
cp "build/plugin-root${QPA_GUEST}" "build/rootfs${QPA_GUEST}"
sha256sum "build/rootfs${QPA_GUEST}" > build/report/qpa-patched.sha256

rm -rf build/qpa-closure
python3 runtime/m3/collect_rootfs.py \
  --source-root build/rootfs \
  --target "$QPA_GUEST" \
  --output-root build/qpa-closure \
  --manifest build/report/qpa-closure.json
python3 - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path('build/report/qpa-closure.json').read_text())
assert manifest['unresolved'] == [], manifest['unresolved']
assert manifest['object_count'] >= 3, manifest
print(json.dumps({
    'object_count': manifest['object_count'],
    'total_size': manifest['total_size'],
    'unresolved': manifest['unresolved'],
}, indent=2))
PY

tar --sort=name --mtime='UTC 2026-01-01' \
  --owner=0 --group=0 --numeric-owner \
  -C build/rootfs -czf build/hword-hrtappkit-rootfs.tar.gz .
sha256sum build/hword-hrtappkit-rootfs.tar.gz \
  > build/hword-hrtappkit-rootfs.tar.gz.sha256
ls -lh build/hword-hrtappkit-rootfs.tar.gz
