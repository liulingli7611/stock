"""Sync embedded constants in the Cursor canvas from output/0050_latest.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "output" / "0050_latest.json"
CANVAS_PATH = (
    Path.home()
    / ".cursor/projects/Users-lily-Documents-Stock/canvases/0050_strategy.canvas.tsx"
)


def _ts_val(v):
    if v is None:
        return "null as number | null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    fund = data["fundamentals"]
    levels = data["levels"]
    bt = data["backtest"]
    equity = [round(e["equity"], 4) for e in data["equity_curve"]]
    dates = [f"{e['date'][2:4]}-{e['date'][5:7]}" for e in data["equity_curve"]]

    as_of = levels["as_of"]
    fund_block = ",\n".join(
        f"  {k}: {_ts_val(fund[k])}"
        for k in (
            "pe_ratio",
            "annualized_volatility_pct",
            "cash_dividend_yield_pct",
            "tsmc_weight_pct",
            "premium_pct",
            "overall_bias",
            "position_cap_pct",
            "pe_bias",
            "vol_bias",
            "premium_bias",
        )
    )
    level_keys = [
        "price",
        "trend_state",
        "ma20",
        "ma60",
        "ma120",
        "rsi14",
        "macd",
        "macd_signal",
        "macd_hist",
        "atr14",
        "bb_lower",
        "bb_mid",
        "bb_upper",
        "vol_ratio",
        "support_near",
        "support_mid",
        "resistance_near",
        "stop_ref",
        "swing_buy_pullback",
        "swing_buy_breakout",
        "target1",
        "target2",
        "zone_a",
        "zone_b",
        "zone_c_trigger",
        "swing_long_allowed",
        "position_size_hint",
    ]
    levels_block = ",\n".join(f"  {k}: {_ts_val(levels[k])}" for k in level_keys)
    bt_block = ",\n".join(
        f"  {k}: {_ts_val(bt[k])}"
        for k in (
            "start",
            "end",
            "trades",
            "win_rate_pct",
            "profit_factor",
            "strategy_total_return_pct",
            "strategy_annualized_pct",
            "strategy_max_drawdown_pct",
            "buyhold_total_return_pct",
            "buyhold_annualized_pct",
            "buyhold_max_drawdown_pct",
        )
    )

    text = CANVAS_PATH.read_text(encoding="utf-8")
    text = re.sub(
        r'const AS_OF = "[^"]*";',
        f'const AS_OF = "{as_of}";',
        text,
        count=1,
    )
    text = re.sub(
        r"const FUND = \{.*?\n\};",
        f"const FUND = {{\n{fund_block},\n}};",
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"const LEVELS = \{.*?\n\};",
        f"const LEVELS = {{\n{levels_block},\n}};",
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"const BT = \{.*?\n\};",
        f"const BT = {{\n{bt_block},\n}};",
        text,
        count=1,
        flags=re.S,
    )
    eq_str = ", ".join(str(x) for x in equity)
    date_str = ", ".join(json.dumps(d) for d in dates)
    text = re.sub(
        r"const EQUITY = \[[^\]]*\];",
        f"const EQUITY = [\n  {eq_str},\n];",
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"const EQUITY_DATES = \[[^\]]*\];",
        f"const EQUITY_DATES = [\n  {date_str},\n];",
        text,
        count=1,
        flags=re.S,
    )
    CANVAS_PATH.write_text(text, encoding="utf-8")
    print(f"Synced canvas → {CANVAS_PATH}")


if __name__ == "__main__":
    main()
