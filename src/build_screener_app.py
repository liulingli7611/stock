"""Build interactive screener frontend HTML with embedded payload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).resolve().parent / "templates" / "screener_app.html"
PLACEHOLDER = "__SCREENER_PAYLOAD__"


def build_screener_app_html(payload: dict[str, Any]) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise RuntimeError(f"Template missing placeholder {PLACEHOLDER}")
    # Compact but valid JSON; ensure </script> cannot break out
    blob = json.dumps(payload, ensure_ascii=False, default=str, allow_nan=False)
    blob = blob.replace("</", "<\\/")
    return template.replace(PLACEHOLDER, blob)


def write_screener_app(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_screener_app_html(payload), encoding="utf-8")
    return path


if __name__ == "__main__":
    import json
    import sys

    json_path = ROOT / "output" / "screener_latest.json"
    if not json_path.exists():
        print(f"Missing {json_path}; run: python -m src.run_screener", file=sys.stderr)
        raise SystemExit(1)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    app = write_screener_app(payload, ROOT / "reports" / "screener_app.html")
    write_screener_app(payload, ROOT / "reports" / "screener_deck.html")
    print(f"Wrote {app}")
