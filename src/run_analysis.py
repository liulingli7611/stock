"""One-shot analysis: fetch → fundamentals → signals → backtest → report/JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import run_swing_backtest
from src.fetch_0050 import fetch_daily, fetch_nav_premium_estimate, fetch_tsmc_daily
from src.fundamentals import build_fundamental_snapshot
from src.signals import attach_trend_state, compute_trade_levels

OUTPUT_DIR = ROOT / "output"
REPORTS_DIR = ROOT / "reports"


def _r(v, nd=2):
    if v is None:
        return "n/a"
    try:
        if pd.isna(v):
            return "n/a"
    except TypeError:
        pass
    return f"{v:.{nd}f}"


def build_report(fund: dict, levels: dict, bt: dict) -> str:
    lines = [
        "# 0050 波段＋中長期策略分析報告",
        "",
        f"**資料日期**：{levels['as_of']} ｜ **現價**：{_r(levels['price'], 2)} ｜ "
        f"**趨勢狀態**：`{levels['trend_state']}`",
        "",
        "> 免責：本報告僅供研究參考，非投資建議。",
        "",
        "## 一、基本面環境濾網",
        "",
        f"| 項目 | 數值 | 偏向 |",
        f"|------|------|------|",
        f"| 加權本益比 P/E | {_r(fund['pe_ratio'])} | {fund['pe_bias']} |",
        f"| 年化波動 | {_r(fund['annualized_volatility_pct'])}% | {fund['vol_bias']} |",
        f"| 折溢價 | {_r(fund['premium_pct'], 3)}% | {fund['premium_bias']} |",
        f"| 台積電權重 | {_r(fund['tsmc_weight_pct'])}% | — |",
        f"| 現金股息率（參考） | {_r(fund['cash_dividend_yield_pct'])}% | — |",
        f"| **整體偏向** | **{fund['overall_bias']}** | 波段部位上限 {fund['position_cap_pct']}% |",
        "",
        f"- 來源：{fund['source_pe']}；{fund['source_tsmc_weight']}",
        f"- 說明：{fund['notes']}",
        "",
        "### 中長期加碼規則",
        "",
        "- 每月資金 **50%** 無條件定投。",
        "- 另 **50%** 僅在 Zone A/B/C 分批投入；`overall_bias=defensive` 時暫停逢低加碼。",
        "",
        "## 二、技術面與趨勢",
        "",
        f"| 指標 | 數值 |",
        f"|------|------|",
        f"| MA20 | {_r(levels['ma20'])} |",
        f"| MA60 | {_r(levels['ma60'])} |",
        f"| MA120 | {_r(levels['ma120'])} |",
        f"| RSI(14) | {_r(levels['rsi14'])} |",
        f"| MACD / Signal / Hist | {_r(levels['macd'], 3)} / {_r(levels['macd_signal'], 3)} / {_r(levels['macd_hist'], 3)} |",
        f"| ATR(14) | {_r(levels['atr14'], 3)} |",
        f"| 布林 下/中/上 | {_r(levels['bb_lower'])} / {_r(levels['bb_mid'])} / {_r(levels['bb_upper'])} |",
        f"| 量能比 (Vol/VolMA20) | {_r(levels['vol_ratio'], 2)} |",
        f"| 波段做多允許 | {levels['swing_long_allowed']}（部位提示：{levels['position_size_hint']}） |",
        f"| 當日訊號 | {', '.join(levels['signals']) if levels['signals'] else '無'} |",
        "",
        "### 趨勢狀態含義",
        "",
        "- `StrongUp`：只做多、回檔買",
        "- `Up`：可做多、縮小部位",
        "- `Range`：高拋低吸、嚴格區間",
        "- `Down`：波段不做多；中長期僅保留 50% 定投",
        "",
        "## 三、價格區間與買賣點（依最新收盤推算）",
        "",
        f"| 類型 | 價位 |",
        f"|------|------|",
        f"| 近端支撐 | {_r(levels['support_near'])} |",
        f"| 中期支撐 (MA60±0.5ATR 下緣) | {_r(levels['support_mid'])} |",
        f"| 近端壓力 | {_r(levels['resistance_near'])} |",
        f"| 回檔買參考 (MA20) | {_r(levels['swing_buy_pullback'])} |",
        f"| 突破買參考 (20日高) | {_r(levels['swing_buy_breakout'])} |",
        f"| 目標1 (+1.5ATR) | {_r(levels['target1'])} |",
        f"| 目標2 | {_r(levels['target2'])} |",
        f"| 硬停損參考 (−1.5ATR) | {_r(levels['stop_ref'])} |",
        f"| 中長期 Zone A (MA20) | {_r(levels['zone_a'])} |",
        f"| 中長期 Zone B | {_r(levels['zone_b'])} |",
        f"| Zone C 觸發 | {levels['zone_c_trigger']}（單月跌>8% 或 RSI<30） |",
        "",
        "### 出場紀律（波段）",
        "",
        "- 目標1 出 50%，目標2 出 30%，其餘 20% 用 MA20／ATR 移動停利。",
        "- 硬停損：進場 −1.5×ATR，或收盤跌破 MA60。",
        "",
        "## 四、簡易回測摘要（波段回檔買）",
        "",
        f"- 區間：{bt['start']} → {bt['end']}（{bt['bars']} 交易日）",
        f"- 交易次數：{bt['trades']}｜勝率：{bt['win_rate_pct']}%｜盈虧比(PF)：{bt['profit_factor']}",
        f"- 策略總報酬：{bt['strategy_total_return_pct']}%｜年化：{bt['strategy_annualized_pct']}%｜最大回撤：{bt['strategy_max_drawdown_pct']}%",
        f"- 買進持有總報酬：{bt['buyhold_total_return_pct']}%｜年化：{bt['buyhold_annualized_pct']}%｜最大回撤：{bt['buyhold_max_drawdown_pct']}%",
        "",
        "## 五、風險提醒",
        "",
        "- 0050 高度暴露台積電權重，波動接近大型科技權值。",
        "- ETF 本益比為持股加權試算，解讀不同於單一公司。",
        "- 公開行情／NAV 可能延遲，下單前請核對券商報價。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching 0050 daily bars...")
    bars = fetch_daily(period="5y", use_cache=False)
    print(f"  rows={len(bars)} last={bars.index[-1].date()} close={bars['Close'].iloc[-1]:.2f}")

    print("Fetching TSMC for cross-check...")
    try:
        tsmc = fetch_tsmc_daily(period="5y")
    except Exception as exc:  # noqa: BLE001
        print(f"  TSMC fetch failed: {exc}")
        tsmc = None

    price = float(bars["Close"].iloc[-1])
    nav_info = fetch_nav_premium_estimate(price)

    fund = build_fundamental_snapshot(
        market_price=price,
        close_series=bars["Close"],
        premium_pct=nav_info.get("premium_pct"),
        nav=nav_info.get("nav"),
        tsmc_df=tsmc,
    )

    print("Computing indicators & levels...")
    enriched = attach_trend_state(bars)
    levels = compute_trade_levels(enriched)

    print("Running backtest...")
    bt = run_swing_backtest(bars)

    fund_d = fund.to_dict()
    levels_d = levels.to_dict()
    bt_d = bt.to_dict()
    # Keep equity in separate file-friendly payload; also embed for canvas
    payload = {
        "fundamentals": fund_d,
        "levels": levels_d,
        "backtest": {k: v for k, v in bt_d.items() if k != "equity_curve"},
        "equity_curve": bt_d["equity_curve"],
        "nav_info": nav_info,
        "disclaimer": "For research only. Not investment advice.",
    }

    json_path = OUTPUT_DIR / "0050_latest.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    bt_path = OUTPUT_DIR / "0050_backtest.json"
    bt_path.write_text(
        json.dumps({k: v for k, v in bt_d.items() if k != "equity_curve"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sig_cols = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "MA20",
        "MA60",
        "MA120",
        "RSI14",
        "MACD",
        "MACD_signal",
        "MACD_hist",
        "BB_lower",
        "BB_mid",
        "BB_upper",
        "ATR14",
        "VOL_MA20",
        "trend_state",
    ]
    enriched[sig_cols].to_csv(OUTPUT_DIR / "0050_signals.csv", index_label="Date")

    report = build_report(fund_d, levels_d, bt_d)
    report_path = REPORTS_DIR / "0050_latest.md"
    report_path.write_text(report, encoding="utf-8")

    # Compact payload for canvas sync
    canvas_payload = {
        "fundamentals": fund_d,
        "levels": levels_d,
        "backtest": {k: v for k, v in bt_d.items() if k != "equity_curve"},
        "equity": [
            {"date": e["date"], "equity": round(e["equity"], 4)} for e in bt_d["equity_curve"]
        ],
    }
    (OUTPUT_DIR / "0050_canvas_payload.json").write_text(
        json.dumps(canvas_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    try:
        from src.sync_canvas import main as sync_canvas

        sync_canvas()
    except Exception as exc:  # noqa: BLE001
        print(f"Canvas sync skipped: {exc}")

    print(f"Wrote {json_path}")
    print(f"Wrote {report_path}")
    print(f"Trend={levels.trend_state} price={levels.price} bias={fund.overall_bias}")


if __name__ == "__main__":
    main()
