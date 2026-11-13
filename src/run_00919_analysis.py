"""00919 one-shot strategy analysis: fetch → fundamentals → signals → backtest → report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import run_swing_backtest
from src.fetch_0050 import _normalize_ohlcv, fetch_daily
from src.fundamentals_00919 import (
    DEFAULT_DIV_YIELD,
    DEFAULT_FINANCIAL_WEIGHT,
    build_fundamental_snapshot_00919,
)
from src.signals import attach_trend_state, compute_trade_levels

OUTPUT_DIR = ROOT / "output"
REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
TICKER = "00919.TW"
FIN_PROXY = "2881.TW"  # 富邦金 — largest holding proxy


def _r(v, nd=2):
    if v is None:
        return "n/a"
    try:
        if pd.isna(v):
            return "n/a"
    except TypeError:
        pass
    return f"{v:.{nd}f}"


def fetch_financial_proxy(period: str = "5y") -> pd.DataFrame:
    raw = yf.download(
        FIN_PROXY,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    return _normalize_ohlcv(raw)


def fetch_nav_premium(market_price: float, ticker: str = TICKER) -> dict:
    result = {
        "nav": None,
        "market_price": market_price,
        "premium_pct": None,
        "source": None,
        "as_of": None,
        "note": "NAV unavailable",
    }
    try:
        info = yf.Ticker(ticker).info or {}
        if info.get("navPrice"):
            nav_v = float(info["navPrice"])
            prem = (market_price / nav_v - 1.0) * 100.0
            if abs(prem) > 1.5:
                result.update(
                    {
                        "nav": round(nav_v, 4),
                        "premium_pct": None,
                        "source": "yfinance.info.navPrice",
                        "note": f"Ignored outlier premium {prem:.2f}%",
                    }
                )
                return result
            result.update(
                {
                    "nav": round(nav_v, 4),
                    "premium_pct": round(prem, 4),
                    "source": "yfinance.info.navPrice",
                    "note": "Estimated premium from yfinance navPrice",
                }
            )
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"yfinance NAV failed: {exc}"
    return result


def build_report(fund: dict, levels: dict, bt: dict) -> str:
    lines = [
        "# 00919 波段＋中長期策略分析報告",
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
        f"| 加權本益比 P/E | {_r(fund.get('pe_ratio'))} | {fund['pe_bias']} |",
        f"| 年化波動 | {_r(fund['annualized_volatility_pct'])}% | {fund['vol_bias']} |",
        f"| 折溢價 | {_r(fund['premium_pct'], 3)}% | {fund['premium_bias']} |",
        f"| 金融股權重 | {_r(fund['financial_weight_pct'])}% | {fund.get('financial_bias', '—')} |",
        f"| 粗估現金殖利率 | {_r(fund['cash_dividend_yield_pct'])}% | — |",
        f"| **整體偏向** | **{fund['overall_bias']}** | 波段部位上限 {fund['position_cap_pct']}% |",
        "",
        f"- 來源：{fund['source_pe']}；{fund['source_financial_weight']}",
        f"- 說明：{fund['notes']}",
        "",
        "### 中長期加碼規則",
        "",
        "- 每月資金 **50%** 無條件定投（現金流部位）。",
        "- 另 **50%** 僅在 Zone A/B/C 分批投入；`overall_bias=defensive` 時暫停逢低加碼。",
        "- 勿把單季配息×4 當成可持續年化報酬；追蹤含息總報酬與配息來源公告。",
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
        "- 00919 金融股權重約五成，利率／壽險評價／金融景氣敏感度高。",
        "- 近期配息可能大量來自已實現資本利得；淨值會同步扣減，勿只看殖利率。",
        "- 換股後風格可能漂移；策略參數與 0050 相同，但標的波動與產業曝險不同。",
        "- 公開行情／NAV／持股以投信與證交所公告為準。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching 00919 daily bars...")
    bars = fetch_daily(
        ticker=TICKER,
        period="5y",
        cache_path=DATA_DIR / "00919_daily.csv",
        use_cache=False,
    )
    print(f"  rows={len(bars)} last={bars.index[-1].date()} close={bars['Close'].iloc[-1]:.2f}")

    print("Fetching financial proxy (2881)...")
    try:
        fin = fetch_financial_proxy(period="5y")
    except Exception as exc:  # noqa: BLE001
        print(f"  proxy fetch failed: {exc}")
        fin = None

    price = float(bars["Close"].iloc[-1])
    nav_info = fetch_nav_premium(price)

    # Naive yield from trailing 4Q if price available (override default when possible)
    trailing_4q = 1.1 + 1.0 + 0.78 + 0.54
    div_yield = round(trailing_4q / price * 100.0, 2) if price > 0 else DEFAULT_DIV_YIELD

    fund = build_fundamental_snapshot_00919(
        market_price=price,
        close_series=bars["Close"],
        premium_pct=nav_info.get("premium_pct"),
        nav=nav_info.get("nav"),
        financial_weight_pct=DEFAULT_FINANCIAL_WEIGHT,
        div_yield=div_yield,
        financial_proxy_df=fin,
    )

    print("Computing indicators & levels...")
    enriched = attach_trend_state(bars)
    levels = compute_trade_levels(enriched)

    print("Running backtest...")
    bt = run_swing_backtest(bars)

    fund_d = fund.to_dict()
    levels_d = levels.to_dict()
    bt_d = bt.to_dict()

    payload = {
        "fundamentals": fund_d,
        "levels": levels_d,
        "backtest": {k: v for k, v in bt_d.items() if k != "equity_curve"},
        "equity_curve": bt_d["equity_curve"],
        "nav_info": nav_info,
        "disclaimer": "For research only. Not investment advice.",
        "ticker": "00919",
    }

    json_path = OUTPUT_DIR / "00919_strategy_latest.json"
    # Also write 00919_latest.json in strategy shape for canvas sync compatibility
    # (watch-eval overwrites were separate; strategy is canonical for ./update)
    (OUTPUT_DIR / "00919_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    (OUTPUT_DIR / "00919_backtest.json").write_text(
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
    enriched[sig_cols].to_csv(OUTPUT_DIR / "00919_signals.csv", index_label="Date")

    report = build_report(fund_d, levels_d, bt_d)
    report_path = REPORTS_DIR / "00919_latest.md"
    report_path.write_text(report, encoding="utf-8")

    canvas_payload = {
        "fundamentals": fund_d,
        "levels": levels_d,
        "backtest": {k: v for k, v in bt_d.items() if k != "equity_curve"},
        "equity": [
            {"date": e["date"], "equity": round(e["equity"], 4)} for e in bt_d["equity_curve"]
        ],
    }
    (OUTPUT_DIR / "00919_canvas_payload.json").write_text(
        json.dumps(canvas_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    try:
        from src.sync_canvas_00919 import main as sync_canvas

        sync_canvas()
    except Exception as exc:  # noqa: BLE001
        print(f"Canvas sync skipped: {exc}")

    try:
        from src.build_00919_deck import main as build_deck

        build_deck()
    except Exception as exc:  # noqa: BLE001
        print(f"Deck build skipped: {exc}")

    print(f"Wrote {json_path}")
    print(f"Wrote {report_path}")
    print(f"Trend={levels.trend_state} price={levels.price} bias={fund.overall_bias}")


if __name__ == "__main__":
    main()
