"""Build the single-file offline prototype from the same markup, styles and script as the app.

    python build_demo.py                      -> ../cashy-review-demo.html
    python build_demo.py path/to/out.html

The output embeds every case (including Cashy's answer and the reference determination)
and replaces the Flask API with an in-page mock, so it is for demos only, never for data collection.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import s8

BASE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE.parent / "cashy-review-demo.html"

HEAD = """<title>Cashy Second Look</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
"""


def main() -> None:
    from app import CASES, ROWS  # reuses the app's paths and validation

    demo = {"cases": []}
    for i, cfg in enumerate(CASES):
        demo["cases"].append({
            "public": s8.public_case(cfg, ROWS, i, len(CASES)),
            "hidden": {"cashy": cfg["cashy"], "reference": s8.reference(ROWS[cfg["s8_row"]])},
            "autofill": cfg["demo_autofill"],
        })
    data = json.dumps(demo, ensure_ascii=False).replace("</", "<\\/")
    css = (BASE / "static" / "style.css").read_text(encoding="utf-8")
    js = (BASE / "static" / "app.js").read_text(encoding="utf-8")
    body = (BASE / "templates" / "body.html").read_text(encoding="utf-8")
    html = (HEAD + "<style>\n" + css + "</style>\n" + body
            + "\n<script>window.CASHY_DEMO = " + data + ";</script>\n<script>\n" + js + "</script>\n")
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(html) // 1024} KB, {len(CASES)} cases)")


if __name__ == "__main__":
    main()
