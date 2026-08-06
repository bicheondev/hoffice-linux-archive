#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SOURCE_FILES = (
    "qoffscreenintegration.cpp",
    "qoffscreenintegration.h",
    "qoffscreenintegration_dummy.cpp",
    "qoffscreencommon.cpp",
    "qoffscreencommon.h",
    "qoffscreenwindow.cpp",
    "qoffscreenwindow.h",
)


def require_replace(text: str, needle: str, replacement: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(needle, replacement, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qtbase", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    qtbase = args.qtbase.resolve()
    overlay = args.overlay.resolve()
    output = args.output.resolve()
    source = qtbase / "src/plugins/platforms/offscreen"
    if not source.is_dir():
        raise RuntimeError(f"Qt offscreen source not found: {source}")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for name in SOURCE_FILES:
        source_file = source / name
        if not source_file.is_file():
            raise RuntimeError(f"missing pinned Qt source: {source_file}")
        shutil.copy2(source_file, output / name)

    for name in ("main.cpp", "qhrthostcall.h", "hrtmac.json", "hrtmac.pro"):
        shutil.copy2(overlay / name, output / name)

    window_path = output / "qoffscreenwindow.cpp"
    window = window_path.read_text(encoding="utf-8")
    window = require_replace(
        window,
        '#include "qoffscreenwindow.h"\n',
        '#include "qoffscreenwindow.h"\n#include "qhrthostcall.h"\n\n'
        '#include <QtCore/qbytearray.h>\n#include <QtCore/qdebug.h>\n',
        "include host-call bridge",
    )
    window = require_replace(
        window,
        "void QOffscreenWindow::setVisible(bool visible)\n{\n    if (visible) {\n",
        "void QOffscreenWindow::setVisible(bool visible)\n{\n"
        "    if (visible && !m_visible) {\n"
        "        QByteArray title = window()->title().toUtf8();\n"
        "        if (title.isEmpty())\n"
        "            title = QByteArrayLiteral(\"한워드 2022 Beta\");\n"
        "        const QRect rect = geometry();\n"
        "        const qint64 request = hrtHostCreateWindow(\n"
        "            title.constData(), title.size(),\n"
        "            quint32(qMax(1, rect.width())),\n"
        "            quint32(qMax(1, rect.height())));\n"
        "        qWarning(\"HRT QPA: QPlatformWindow AppKit request id=%lld \"\n"
        "                 \"title=%s size=%dx%d\",\n"
        "                 static_cast<long long>(request),\n"
        "                 title.constData(), rect.width(), rect.height());\n"
        "    }\n"
        "    if (visible) {\n",
        "instrument QOffscreenWindow::setVisible",
    )
    window_path.write_text(window, encoding="utf-8")

    print(f"prepared custom QPA source at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
