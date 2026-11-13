"""CLI: screen constituent ETFs → CSV / JSON / Markdown / HTML.

Research reference only — not investment advice.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.build_screener_app import write_screener_app
from src.catalog import load_catalog
from src.screener import apply_scores, run_screener, top_slices
from src.screener_config import ScreenerConfig, config_from_args
from src.tech_filters import catalog_public

OUTPUT_DIR = ROOT / "output"
REPORTS_DIR = ROOT / "reports"

DISCLAIMER = "研究參考用途，不構成投資建議。作空僅提供價格區間參考。"


def _fmt_pct(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return f"{float(x) * 100:.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(x: Any, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _json_safe(value: Any) -> Any:
    """Replace NaN/Inf so dumps/fetch stay strict-JSON / JS-parseable."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    # numpy scalar
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (ValueError, TypeError, AttributeError):
            pass
    try:
        if pd.isna(value):
            return None
    except (ValueError, TypeError):
        pass
    return value


def _jsonish_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = df.to_dict(orient="records")
    for rec in records:
        for key in ("category_ids", "category_names"):
            val = rec.get(key)
            if isinstance(val, str):
                rec[key] = [p for p in val.split("|") if p]
            elif val is None or (isinstance(val, float) and pd.isna(val)):
                rec[key] = []
            elif not isinstance(val, list):
                rec[key] = list(val) if val is not None else []
        if rec.get("custom") is None or (isinstance(rec.get("custom"), float) and pd.isna(rec.get("custom"))):
            rec["custom"] = rec.get("etf_membership") == "custom"
        rec["custom"] = bool(rec["custom"])
        weights = rec.get("weights")
        if isinstance(weights, str):
            try:
                weights = json.loads(weights)
            except json.JSONDecodeError:
                weights = {}
        if not isinstance(weights, dict):
            weights = {}
        clean = {}
        for code, value in weights.items():
            try:
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    continue
                clean[str(code)] = float(value)
            except (TypeError, ValueError):
                continue
        rec["weights"] = clean
        members = rec.get("member_etfs")
        if isinstance(members, str):
            members = [p for p in members.split("+") if p]
        elif not isinstance(members, list):
            members = list(clean.keys())
        rec["member_etfs"] = [str(x) for x in members]
        for key, value in list(rec.items()):
            rec[key] = _json_safe(value)
    return records


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in ("category_ids", "category_names"):
        if col in out.columns:
            out[col] = out[col].apply(
                lambda x: "|".join(x) if isinstance(x, list) else ("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))
            )
    out.to_csv(path, index=False)


def build_payload(df: pd.DataFrame, cfg: ScreenerConfig) -> dict[str, Any]:
    longs, shorts, watch = top_slices(df, cfg.top_n)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
        "config": cfg.to_dict(),
        "tech_filters": {
            "enabled": list(cfg.tech_filters),
            "filters": catalog_public(),
            "ready": {},
        },
        "catalog": load_catalog(),
        "counts": {
            "universe": int(len(df)),
            "long_candidate": int((df["label"] == "long_candidate").sum()),
            "short_candidate": int((df["label"] == "short_candidate").sum()),
            "watch": int((df["label"] == "watch").sum()),
            "skip": int((df["label"] == "skip").sum()),
        },
        "long_candidates": _jsonish_records(longs),
        "short_candidates": _jsonish_records(shorts),
        "watch": _jsonish_records(watch),
        "all": _jsonish_records(df),
    }


def write_json(df: pd.DataFrame, cfg: ScreenerConfig, path: Path) -> dict[str, Any]:
    payload = build_payload(df, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )
    return payload


def _md_table(df: pd.DataFrame, side: str) -> list[str]:
    if df.empty:
        return ["（無）", ""]
    lines = [
        "| 代碼 | 名稱 | 來源 | 價 | 趨勢 | PE | 殖利率 | 分數 | 進場 | 停損 | 目標1 | 目標2 |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    score_col = "long_score" if side == "long" else "short_score"
    entry_col = "long_entry" if side == "long" else "short_entry"
    stop_col = "long_stop" if side == "long" else "short_stop"
    t1_col = "long_target1" if side == "long" else "short_target1"
    t2_col = "long_target2" if side == "long" else "short_target2"
    for _, r in df.iterrows():
        lines.append(
            "| {ticker} | {name} | {etf} | {price} | {trend} | {pe} | {dy} | {score} | {entry} | {stop} | {t1} | {t2} |".format(
                ticker=r["ticker"],
                name=str(r["name"])[:10],
                etf=r["etf_membership"],
                price=_fmt_num(r["price"]),
                trend=r["trend_state"],
                pe=_fmt_num(r["trailing_pe"]),
                dy=_fmt_pct(r["dividend_yield"]),
                score=_fmt_num(r[score_col], 2),
                entry=_fmt_num(r[entry_col]),
                stop=_fmt_num(r[stop_col]),
                t1=_fmt_num(r[t1_col]),
                t2=_fmt_num(r[t2_col]),
            )
        )
    lines.append("")
    return lines


def write_markdown(df: pd.DataFrame, cfg: ScreenerConfig, path: Path) -> None:
    longs, shorts, watch = top_slices(df, cfg.top_n)
    pe_med = df["pe_median_universe"].iloc[0] if "pe_median_universe" in df.columns else None
    lines = [
        "# 成份股選股器",
        "",
        f"> {DISCLAIMER}",
        "",
        f"產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 參數",
        "",
        f"| 參數 | 值 |",
        f"|---|---|",
        f"| universe | {cfg.universe} |",
        f"| min_yield | {cfg.min_yield} |",
        f"| max_pe / min_pe_short | {cfg.max_pe} / {cfg.min_pe_short} |",
        f"| pe_vs_median_max | {cfg.pe_vs_median_max} |",
        f"| 作多 atr_stop / target1 / target2 | {cfg.atr_stop} / {cfg.atr_target1} / {cfg.atr_target2} |",
        f"| 作空 atr_stop / target1 / target2 | {cfg.atr_stop_short} / {cfg.atr_target1_short} / {cfg.atr_target2_short} |",
        f"| rsi_long_max / rsi_short_min | {cfg.rsi_long_max} / {cfg.rsi_short_min} |",
        f"| tech_filters | {', '.join(cfg.tech_filters) or '（無）'} |",
        f"| long_trends | {', '.join(cfg.long_trends)} |",
        f"| short_trends | {', '.join(cfg.short_trends)} |",
        f"| universe PE median | {_fmt_num(pe_med)} |",
        f"| names scanned | {len(df)} |",
        "",
        "## 作多候選",
        "",
    ]
    lines.extend(_md_table(longs, "long"))
    lines.extend(["## 作空候選", ""])
    lines.extend(_md_table(shorts, "short"))
    lines.extend(["## 觀察", ""])
    lines.extend(_md_table(watch, "long"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def persist_outputs(df: pd.DataFrame, cfg: ScreenerConfig) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "screener_latest.csv"
    json_path = OUTPUT_DIR / "screener_latest.json"
    md_path = REPORTS_DIR / "screener_latest.md"
    app_path = REPORTS_DIR / "screener_app.html"
    deck_path = REPORTS_DIR / "screener_deck.html"

    write_csv(df, csv_path)
    payload = write_json(df, cfg, json_path)
    write_markdown(df, cfg, md_path)
    write_screener_app(payload, app_path)
    write_screener_app(payload, deck_path)
    return payload


def load_latest_frame() -> Optional[pd.DataFrame]:
    path = OUTPUT_DIR / "screener_latest.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("all") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def upsert_analyzed_row(row: dict[str, Any], cfg: Optional[ScreenerConfig] = None) -> dict[str, Any]:
    cfg = cfg or ScreenerConfig(universe="all")
    existing = load_latest_frame()
    if existing is None or existing.empty:
        df = pd.DataFrame([row])
    else:
        df = existing.copy()
        ticker = str(row["ticker"]).zfill(4)
        if "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.zfill(4)
            df = df[df["ticker"] != ticker]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = apply_scores(df, cfg)
    return persist_outputs(df, cfg)


def main(cfg: Optional[ScreenerConfig] = None, progress_cb=None) -> int:
    cfg = cfg or config_from_args()
    print("Running screener — research reference only, not investment advice.")
    df = run_screener(cfg, ROOT, progress_cb=progress_cb)
    persist_outputs(df, cfg)

    longs, shorts, _ = top_slices(df, cfg.top_n)
    csv_path = OUTPUT_DIR / "screener_latest.csv"
    json_path = OUTPUT_DIR / "screener_latest.json"
    md_path = REPORTS_DIR / "screener_latest.md"
    app_path = REPORTS_DIR / "screener_app.html"
    print(f"Done. long={len(longs)} short={len(shorts)} scanned={len(df)}")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"APP:  {app_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
