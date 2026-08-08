#!/bin/bash
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${PREPARED_RUN_ID:?PREPARED_RUN_ID is required}"
: "${HOST_RUN_ID:?HOST_RUN_ID is required}"
: "${QPA_RUN_ID:?QPA_RUN_ID is required}"
: "${ASSET_NAME:?ASSET_NAME is required}"
: "${RELEASE_TAG:?RELEASE_TAG is required}"
: "${PACKAGE_SHA256:?PACKAGE_SHA256 is required}"
: "${PROGRAM:?PROGRAM is required}"
: "${PROGRAM_SHA256:?PROGRAM_SHA256 is required}"
: "${HWORD_APP_GUEST:?HWORD_APP_GUEST is required}"
: "${HWORD_APP_SHA256:?HWORD_APP_SHA256 is required}"
: "${HWORD_APP_PATCHED_SHA256:?HWORD_APP_PATCHED_SHA256 is required}"
: "${PLUGIN_GUEST:?PLUGIN_GUEST is required}"

mkdir -p build/input/prepared build/input/host build/input/qpa \
         build/input/deb build/host build/proof diagnostics proofs

artifact_download() {
    local run_id="$1"
    local name="$2"
    local destination="$3"
    local metadata="build/input/artifacts-${run_id}.json"
    local artifact_id

    gh api --paginate \
        "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/artifacts?per_page=100" \
        >"$metadata"
    artifact_id=$(python3 - "$metadata" "$name" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
items = [item for item in payload.get('artifacts', [])
         if item.get('name') == sys.argv[2] and not item.get('expired')]
if len(items) != 1:
    raise SystemExit(
        f"expected one live artifact named {sys.argv[2]!r}, found {items}")
print(items[0]['id'])
PY
)
    mkdir -p "$destination"
    gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}/zip" \
        >"${destination}/artifact.zip"
    ditto -x -k "${destination}/artifact.zip" "$destination"
    rm -f "${destination}/artifact.zip"
    printf '%s\t%s\t%s\n' "$run_id" "$name" "$artifact_id" \
        >>build/proof/source-artifacts.tsv
}

artifact_download "$PREPARED_RUN_ID" \
    hrt-m9-bootstrap-prepared-guest build/input/prepared
artifact_download "$HOST_RUN_ID" \
    hrt-m10-hword-main-window-input-proof build/input/host
artifact_download "$QPA_RUN_ID" \
    hrt-m8-qt5113-hrtappkit-input-qpa build/input/qpa

gh release download "$RELEASE_TAG" \
    --repo "$GITHUB_REPOSITORY" --pattern "$ASSET_NAME" \
    --dir build/input/deb
printf '%s  %s\n' "$PACKAGE_SHA256" \
    "build/input/deb/$ASSET_NAME" | shasum -a 256 -c -

prepared=$(find build/input/prepared -type f \
    -name hword-m9-prepared-rootfs.tar.zst -print -quit)
checksum=$(find build/input/prepared -type f \
    -name hword-m9-prepared-rootfs.tar.zst.sha256 -print -quit)
test -n "$prepared"; test -n "$checksum"
expected=$(awk '{print $1; exit}' "$checksum")
actual=$(shasum -a 256 "$prepared" | awk '{print $1}')
test "$actual" = "$expected"

image="$RUNNER_TEMP/hrt-m11-korean-staged.sparsebundle"
root="/tmp/h11ks-${GITHUB_RUN_ID}"
rm -rf "$image" "$root"
mkdir -p "$root"
if ! hdiutil create -quiet -size 14g -fs APFSX \
     -volname HRTM11KS -type SPARSEBUNDLE "$image"; then
    rm -rf "$image"
    hdiutil create -quiet -size 14g -fs HFSX \
        -volname HRTM11KS -type SPARSEBUNDLE "$image"
fi
hdiutil attach -quiet -nobrowse -mountpoint "$root" "$image"
cleanup() {
    hdiutil detach -quiet "$root" >/dev/null 2>&1 || true
}
trap cleanup EXIT

zstd -dc "$prepared" | tar -xf - -C "$root"
test -s "$root/.hrt-prepatched-v1"
test -f "$root$PROGRAM"
test -f "$root$HWORD_APP_GUEST"
test "$(readlink "$root/opt/hnc/hoffice1")" = hoffice11

# Restore only the exact package resources proven absent at the M10 frontier.
deb="build/input/deb/$ASSET_NAME"
data_member=$(ar t "$deb" | awk '/^data\.tar/{print; exit}')
test -n "$data_member"
ar p "$deb" "$data_member" >"build/input/deb/$data_member"
tar -xf "build/input/deb/$data_member" -C "$root" \
    ./opt/hnc/hoffice11/Bin/Code \
    ./opt/hnc/hoffice11/Bin/HwordAction.so \
    ./opt/hnc/hoffice11/Bin/libHncImm.KOR.res \
    ./opt/hnc/hoffice11/Bin/libHncOfficeFramework.KOR.res \
    ./opt/hnc/hoffice11/Bin/libHncOfficeFramework.res \
    ./opt/hnc/hoffice11/Bin/optionInfo.xml \
    ./opt/hnc/hoffice11/Bin/themeInfo.xml \
    ./opt/hnc/hoffice11/Bin/qt/translations/qt_en.qm \
    ./opt/hnc/hoffice11/Bin/qt/translations/qt_ko.qm
printf '%s  %s\n' \
    e6de430ac740865928cf3947d1a7a90bf7e5df37d609e85a86051d99d3949cbc \
    "$root/opt/hnc/hoffice11/Bin/HwordAction.so" \
    | shasum -a 256 -c -
find "$root/opt/hnc/hoffice11/Bin/Code" -type f \
    | LC_ALL=C sort >build/proof/restored-code-files.txt
test "$(wc -l <build/proof/restored-code-files.txt | tr -d ' ')" -ge 17

mkdir -p "$root$(dirname "$PLUGIN_GUEST")"
qpa_xz=$(find build/input/qpa -type f -name libqhrtappkit.so.xz -print -quit)
qpa_lock=$(find build/input/qpa -type f -name lock.json -print -quit)
test -n "$qpa_xz"; test -n "$qpa_lock"
python3 - "$qpa_xz" "$qpa_lock" "$root$PLUGIN_GUEST" <<'PY'
import hashlib
import json
import lzma
import pathlib
import sys

compressed = pathlib.Path(sys.argv[1]).read_bytes()
lock = json.loads(pathlib.Path(sys.argv[2]).read_text())
assert lock['toolchain']['qt_version'] == '5.11.3', lock
assert lock['plugin']['m8_input_poll_transport'] is True, lock
assert lock['plugin']['input_poll_opcode'] == 262, lock
assert hashlib.sha256(compressed).hexdigest() == lock['plugin']['xz_sha256']
plugin = lzma.decompress(compressed)
assert hashlib.sha256(plugin).hexdigest() == \
    lock['plugin']['sha256_after_prepatch']
pathlib.Path(sys.argv[3]).write_bytes(plugin)
pathlib.Path('build/proof/qpa-lock.json').write_text(
    json.dumps(lock, indent=2) + '\n')
PY
chmod 0755 "$root$PLUGIN_GUEST"

printf '%s  %s\n' "$HWORD_APP_SHA256" \
    "$root$HWORD_APP_GUEST" | shasum -a 256 -c -
python3 runtime/m9/patch_hword_utility_culture_redirect.py \
    "$root$HWORD_APP_GUEST" \
    --expected-sha256 "$HWORD_APP_SHA256" \
    --expected-output-sha256 "$HWORD_APP_PATCHED_SHA256" \
    --manifest build/proof/culture-redirect-patch.json
printf '%s  %s\n' "$HWORD_APP_PATCHED_SHA256" \
    "$root$HWORD_APP_GUEST" | shasum -a 256 -c -

diskutil info "$root" | tee build/proof/guest-volume.txt
grep -F 'Case-sensitive' build/proof/guest-volume.txt

host=$(find build/input/host -type f \
    -name hrt-m10-hword-main-input -print -quit)
test -n "$host"; test -f "$host"
cp "$host" build/host/hrt-m11-korean-staged
chmod 0755 build/host/hrt-m11-korean-staged
codesign --force --sign - --timestamp=none \
    build/host/hrt-m11-korean-staged
codesign --verify --strict build/host/hrt-m11-korean-staged
file build/host/hrt-m11-korean-staged | tee build/proof/host-file.txt
shasum -a 256 build/host/hrt-m11-korean-staged \
    | tee build/proof/host-sha256.txt

export HRT_M6_CAPTURE_PATH="$PWD/build/proof/pre-frame-window.png"
export HRT_M7_CAPTURE_PATH="$PWD/build/proof/hword-main-window.png"
export HRT_M10_PRE_INPUT_CAPTURE_PATH="$PWD/build/proof/hword-before-input.png"
export HRT_M10_POST_INPUT_CAPTURE_PATH="$PWD/build/proof/hword-after-input.png"
export HRT_M8_SYNTHETIC_INPUT=1
: >build/proof/stdout.txt
: >build/proof/stderr.txt
set +e
/usr/bin/arch -x86_64 build/host/hrt-m11-korean-staged \
    --root "$root" --program "$PROGRAM" \
    >build/proof/stdout.txt 2>build/proof/stderr.txt &
pid=$!
set -e

for _ in $(jot 1800); do
    recent=$(tail -n 8000 build/proof/stderr.txt 2>/dev/null || true)
    if grep -q 'HRT M10 APPKIT: post-input capture result=1' <<<"$recent"; then
        sleep 4
        break
    fi
    if grep -q 'fatal signal' <<<"$recent"; then
        break
    fi
    if grep -q 'HRT M6 QPA: CREATE .*title=Exception ' <<<"$recent"; then
        sleep 2
        break
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        break
    fi
    sleep 0.05
done

alive=0
if kill -0 "$pid" 2>/dev/null; then
    alive=1
    ps -o pid,ppid,state,%cpu,%mem,etime,command -p "$pid" \
        >build/proof/process.txt 2>&1 || true
    /usr/bin/sample "$pid" 2 1 -file build/proof/sample.txt \
        >/dev/null 2>&1 || true
    kill -TERM "$pid" 2>/dev/null || true
    sleep 0.3
    kill -KILL "$pid" 2>/dev/null || true
fi
set +e
wait "$pid"
raw_status=$?
set -e
printf '%s\n' "$raw_status" >build/proof/raw-exit-status.txt
printf '%s\n' "$alive" >build/proof/alive-at-observation.txt

grep -E 'HRT M6 QPA: CREATE |HRT M7 QPA|HRT M8 APPKIT|HRT M8 QPA|HRT M10 QPA|HRT M10 WIDGET|HRT M10 FOCUS|HRT M10 APPKIT|HRT M11 QPA|host-call opcode=262|fatal signal|basic_string::substr|Caught exception|Linux syscall ENOSYS' \
    build/proof/stderr.txt | tail -n 70000 \
    | tee build/proof/key-lines.txt || true
tail -n 24000 build/proof/stderr.txt >build/proof/stderr-tail.txt

python3 - <<'PY'
import hashlib
import json
import os
import re
import struct
from pathlib import Path

stderr = Path('build/proof/stderr.txt').read_text(errors='replace')
titles = []
geometries = []
for line in re.findall(r'HRT M6 QPA: CREATE .*', stderr):
    title = re.search(r' title=(.*?) handle=', line)
    geometry = re.search(r' geometry=(\d+)x(\d+)', line)
    if title:
        titles.append(title.group(1))
    if geometry:
        geometries.append([int(geometry.group(1)), int(geometry.group(2))])

widget_lines = re.findall(r'HRT M10 WIDGET: .*', stderr)
focus_lines = re.findall(r'HRT M10 FOCUS: .*', stderr)
boundary_lines = re.findall(r'HRT M11 QPA: mouse-up stage boundary .*', stderr)
key_lines = re.findall(r'HRT M8 QPA: key event delivered .*', stderr)
mouse_lines = re.findall(r'HRT M8 QPA: mouse event delivered .*', stderr)
accepted_keys = [line for line in key_lines
                 if re.search(r'accepted=1(?:\s|$)', line)]
direct_keys = [line for line in key_lines
               if re.search(r'direct-accepted=1(?:\s|$)', line)]
accepted_mouse = [line for line in mouse_lines
                  if re.search(r'widget-accepted=1(?:\s|$)', line)]
button_clicks = [line for line in focus_lines
                 if 'abstract button click invoked' in line]
selected_focus = [line for line in focus_lines
                  if 'selected receiver=' in line]
candidate_classes = re.findall(
    r'HRT M10 FOCUS: candidate=.*? class=([^\s]+)', stderr)
selected_classes = re.findall(
    r'HRT M10 FOCUS: selected .*? class=([^\s]+)', stderr)
key_target_classes = re.findall(
    r'HRT M10 WIDGET: phase=key-target .*?class=([^\s]+)', stderr)
sequences = [int(value) for value in re.findall(
    r'HRT M8 QPA: (?:key|mouse) event delivered sequence=(\d+)', stderr)]
ordered = sequences == sorted(sequences) and len(sequences) == len(set(sequences))

def png(path_string):
    path = Path(path_string)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    width, height = struct.unpack('>II', data[16:24])
    return {'path': str(path), 'width': width, 'height': height,
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

main_capture = png('build/proof/hword-main-window.png')
before = png('build/proof/hword-before-input.png')
after = png('build/proof/hword-after-input.png')
visual_change = bool(before and after and before['sha256'] != after['sha256'])
main_window = any(title in {'Word', '한워드'} and geometry == [800, 600]
                  for title, geometry in zip(titles, geometries))
exception = 'Exception' in titles or 'Initialization Error' in titles
fatal = 'fatal signal' in stderr
substring = any(token in stderr for token in (
    'basic_string::substr', 'std::out_of_range', '__pos (which is'))
queue_drained = 'HRT M8 QPA: input queue drained' in stderr
post_capture = 'HRT M10 APPKIT: post-input capture result=1' in stderr
alive = bool(int(Path('build/proof/alive-at-observation.txt').read_text()))
unsupported = sorted({int(match.group(1))
                      for line in stderr.splitlines()
                      if (match := re.search(
                          r'Linux syscall ENOSYS\s+([0-9]+)', line))})
markers = {
    'toolbar': 'HRT M10 APPKIT: staged toolbar new-document click' in stderr,
    'focus': 'HRT M10 APPKIT: staged document focus click' in stderr,
    'text': 'HRT M10 APPKIT: staged text input after focus' in stderr,
}
stage_separated = len(boundary_lines) >= 2

document_interaction = bool(
    main_window and not exception and not fatal and not substring and alive and
    ordered and markers['toolbar'] and markers['focus'] and button_clicks and
    accepted_mouse and stage_separated and before)
text_interaction = bool(
    document_interaction and markers['text'] and accepted_keys and
    post_capture and visual_change)

if text_interaction:
    classification = 'HWORD_TEXT_KEY_ACCEPTED_AFTER_KOREAN_TITLE_STAGING'
    status = 'PASS'
elif document_interaction:
    classification = 'HWORD_DOCUMENT_CREATED_AND_FOCUSED_KEY_REJECTED'
    status = 'PARTIAL_PASS'
elif fatal:
    classification = 'HWORD_KOREAN_STAGED_INPUT_FATAL'
    status = 'DIAGNOSTIC'
elif exception:
    classification = 'HWORD_KOREAN_STAGED_INPUT_EXCEPTION'
    status = 'DIAGNOSTIC'
elif not main_window:
    classification = 'HWORD_KOREAN_STAGED_INPUT_NO_MAIN_WINDOW'
    status = 'DIAGNOSTIC'
elif not markers['toolbar']:
    classification = 'HWORD_KOREAN_TITLE_STAGING_NOT_ACTIVE'
    status = 'DIAGNOSTIC'
else:
    classification = 'HWORD_KOREAN_STAGED_INPUT_NOT_ACCEPTED'
    status = 'DIAGNOSTIC'

result = {
    'schema': 3,
    'milestone': 'M11-korean-hword-input',
    'status': status,
    'classification': classification,
    'workflow_run': os.environ['GITHUB_RUN_ID'],
    'commit': os.environ['GITHUB_SHA'],
    'host_run': os.environ['HOST_RUN_ID'],
    'qpa_run': os.environ['QPA_RUN_ID'],
    'prepared_run': os.environ['PREPARED_RUN_ID'],
    'program': os.environ['PROGRAM'],
    'program_sha256': os.environ['PROGRAM_SHA256'],
    'package_sha256': os.environ['PACKAGE_SHA256'],
    'window_titles': titles,
    'window_geometries': geometries,
    'main_window_observed': main_window,
    'staged_markers': markers,
    'stage_boundary_count': len(boundary_lines),
    'stage_boundaries': boundary_lines,
    'widget_log_count': len(widget_lines),
    'focus_log_count': len(focus_lines),
    'button_click_count': len(button_clicks),
    'candidate_widget_classes': candidate_classes,
    'selected_focus_classes': selected_classes,
    'key_target_classes': key_target_classes,
    'mouse_event_count': len(mouse_lines),
    'widget_accepted_mouse_count': len(accepted_mouse),
    'key_event_count': len(key_lines),
    'accepted_key_count': len(accepted_keys),
    'directly_accepted_key_count': len(direct_keys),
    'delivered_sequences': sequences,
    'strictly_ordered_unique_sequences': ordered,
    'queue_drained': queue_drained,
    'post_capture_completed': post_capture,
    'main_capture': main_capture,
    'before_capture': before,
    'after_capture': after,
    'visual_change': visual_change,
    'document_interaction_credited': document_interaction,
    'text_interaction_credited': text_interaction,
    'unsupported_syscalls': unsupported,
    'fatal_signal_observed': fatal,
    'substr_exception_observed': substring,
    'alive_at_observation': alive,
    'raw_exit_status': int(Path('build/proof/raw-exit-status.txt').read_text()),
    'representative_button_clicks': button_clicks[-20:],
    'representative_focus_selection': selected_focus[-60:],
    'representative_key_events': key_lines[-20:],
    'stderr_tail': stderr[-18000:],
}
payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
run_id = os.environ['GITHUB_RUN_ID']
Path(f'diagnostics/m11-korean-title-staged-{run_id}.json').write_text(payload)
Path('diagnostics/m11-korean-title-staged-latest.json').write_text(payload)
Path('diagnostics/m11-korean-title-staged-latest.md').write_text(
    '# Korean HWord title-aware staged input\n\n'
    f'- Status: `{status}`\n'
    f'- Classification: `{classification}`\n'
    f'- Windows: `{list(zip(titles, geometries))}`\n'
    f'- Staged markers: `{markers}`\n'
    f'- Stage boundaries: `{len(boundary_lines)}`\n'
    f'- Button clicks: `{len(button_clicks)}`\n'
    f'- Accepted mouse events: `{len(accepted_mouse)}`\n'
    f'- Accepted key events: `{len(accepted_keys)}`\n'
    f'- Visual change: `{visual_change}`\n'
    f'- Document interaction: `{document_interaction}`\n'
    f'- Text interaction: `{text_interaction}`\n'
    f'- Unsupported syscalls: `{unsupported}`\n')
Path('build/proof/summary.json').write_text(payload)
if status in {'PASS', 'PARTIAL_PASS'}:
    Path('proofs/m11-hword-document-interaction.json').write_text(payload)
if status == 'PASS':
    Path('proofs/m11-hword-text-input.json').write_text(payload)
print(payload)
PY
