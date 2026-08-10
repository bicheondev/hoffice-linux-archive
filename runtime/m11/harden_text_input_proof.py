#!/usr/bin/env python3
"""Harden M11 text-input credit against application-chrome acceptance.

Qt's window-system key path can report an accepted event while focus remains on
``QTabBar``.  That proves the native key packet is valid, but it does not prove
that HWord's editor accepted text.  This post-classifier rewrites the staged
replay result after the raw harness has finished and grants text credit only
when the QPA names a credible editor receiver.

A credible route is either:

* ``credible-accepted=1`` from the guarded window-system path, or
* a directly accepted key whose key-target class is an editor/canvas class.

The script is idempotent, preserves the broader document-interaction proof, and
removes a stale text proof whenever the stricter gate does not pass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


CREDIBLE_CLASS = re.compile(
    r"(?:^|::)(?:HwordAppView|[^\s:]*Editor[^\s:]*|[^\s:]*Canvas[^\s:]*)$"
    r"|^(?:QTextEdit|QPlainTextEdit|QLineEdit)$",
    re.IGNORECASE,
)


def credible_class(name: str) -> bool:
    return bool(CREDIBLE_CLASS.search(name))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("diagnostics/m11-korean-title-staged-latest.json"),
    )
    parser.add_argument(
        "--stderr",
        type=Path,
        default=Path("build/proof/stderr.txt"),
    )
    parser.add_argument(
        "--proof-dir",
        type=Path,
        default=Path("proofs"),
    )
    args = parser.parse_args()

    result = json.loads(args.summary.read_text(encoding="utf-8"))
    stderr = args.stderr.read_text(encoding="utf-8", errors="replace")

    credible_window_lines = re.findall(
        r"HRT M11 KEYROUTE: extended window key .*?"
        r"credible-accepted=1 .*?receiver-class=([^\s]+)",
        stderr,
    )
    credible_window_classes = [
        name for name in credible_window_lines if credible_class(name)
    ]

    direct_lines = re.findall(
        r"HRT M10 QPA: direct key fallback receiver=.*?class=([^\s]+).*?"
        r"accepted=1 .*?type=(\d+)",
        stderr,
    )
    credible_direct_classes = [
        name for name, event_type in direct_lines
        if event_type == "6" and credible_class(name)
    ]

    credible_press_lines = re.findall(
        r"HRT M11 KEYROUTE: extended window key type=6 .*?"
        r"credible-accepted=1 .*?receiver-class=([^\s]+)",
        stderr,
    )
    credible_press_classes = [
        name for name in credible_press_lines if credible_class(name)
    ] + credible_direct_classes

    raw_chrome_acceptance = re.findall(
        r"HRT M11 KEYROUTE: extended window key .*?raw-accepted=1 "
        r"credible-accepted=0 .*?receiver-class=([^\s]+)",
        stderr,
    )
    legacy_chrome_acceptance = re.findall(
        r"HRT M8 QPA: key event delivered .*?accepted=1 .*?"
        r"focus-class=(QTabBar|QTabWidget|QStackedWidget|QToolButton)",
        stderr,
    )

    editor_materialized_classes = re.findall(
        r"HRT M11 KEYROUTE: credible editor materialized .*?class=([^\s]+)",
        stderr,
    )
    prepared_classes = re.findall(
        r"HRT M11 KEYROUTE: prepared focus receiver=.*?class=([^\s]+) "
        r"credible=1",
        stderr,
    )

    document_interaction = bool(result.get("document_interaction_credited"))
    post_capture = bool(result.get("post_capture_completed"))
    visual_change = bool(result.get("visual_change"))
    credible_key_press = bool(credible_press_classes)
    text_interaction = bool(
        document_interaction and post_capture and visual_change and
        credible_key_press
    )

    if text_interaction:
        result["status"] = "PASS"
        result["classification"] = (
            "HWORD_TEXT_KEY_ACCEPTED_BY_CREDIBLE_EDITOR"
        )
    elif document_interaction:
        result["status"] = "PARTIAL_PASS"
        if raw_chrome_acceptance or legacy_chrome_acceptance:
            result["classification"] = (
                "HWORD_CHROME_ACCEPTED_KEY_EDITOR_NOT_PROVEN"
            )
        elif editor_materialized_classes or prepared_classes:
            result["classification"] = (
                "HWORD_EDITOR_MATERIALIZED_KEY_REJECTED"
            )
        else:
            result["classification"] = (
                "HWORD_DOCUMENT_CREATED_EDITOR_NOT_MATERIALIZED"
            )

    result["schema"] = max(int(result.get("schema", 0)), 4)
    result["text_interaction_credited"] = text_interaction
    result["credible_editor_key_press"] = credible_key_press
    result["credible_window_receiver_classes"] = sorted(
        set(credible_window_classes)
    )
    result["credible_direct_receiver_classes"] = sorted(
        set(credible_direct_classes)
    )
    result["editor_materialized_classes"] = sorted(
        set(editor_materialized_classes)
    )
    result["prepared_editor_classes"] = sorted(set(prepared_classes))
    result["raw_chrome_acceptance_classes"] = sorted(
        set(raw_chrome_acceptance + legacy_chrome_acceptance)
    )
    result["proof_gate"] = (
        "credible HWord editor KeyPress acceptance plus post-capture visual change"
    )

    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    run_id = str(result["workflow_run"])
    Path(f"diagnostics/m11-korean-title-staged-{run_id}.json").write_text(
        payload, encoding="utf-8"
    )
    Path("diagnostics/m11-korean-title-staged-latest.json").write_text(
        payload, encoding="utf-8"
    )
    Path("build/proof/summary.json").write_text(payload, encoding="utf-8")
    Path("diagnostics/m11-korean-title-staged-latest.md").write_text(
        "# Korean HWord title-aware staged input\n\n"
        f"- Status: `{result['status']}`\n"
        f"- Classification: `{result['classification']}`\n"
        f"- Credible editor key press: `{credible_key_press}`\n"
        f"- Editor classes: `{sorted(set(editor_materialized_classes))}`\n"
        f"- Credible window receivers: `{sorted(set(credible_window_classes))}`\n"
        f"- Credible direct receivers: `{sorted(set(credible_direct_classes))}`\n"
        f"- Chrome-only acceptance: `{sorted(set(raw_chrome_acceptance + legacy_chrome_acceptance))}`\n"
        f"- Visual change: `{visual_change}`\n",
        encoding="utf-8",
    )

    args.proof_dir.mkdir(parents=True, exist_ok=True)
    document_proof = args.proof_dir / "m11-hword-document-interaction.json"
    text_proof = args.proof_dir / "m11-hword-text-input.json"
    if result["status"] in {"PASS", "PARTIAL_PASS"}:
        document_proof.write_text(payload, encoding="utf-8")
    if text_interaction:
        text_proof.write_text(payload, encoding="utf-8")
    elif text_proof.exists():
        text_proof.unlink()

    print(payload)


if __name__ == "__main__":
    main()
