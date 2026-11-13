"""Evaluate whether 00919 (群益台灣精選高息) is worth watching.

Produces reports/00919_watch_eval.md and output/00919_watch_*.json.
Strategy report lives in run_00919_analysis → reports/00919_latest.md.
Research only — not investment advice.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fetch_0050 import fetch_daily
from src.signals import attach_trend_state, compute_trade_levels

OUTPUT_DIR = ROOT / "output"
REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"

# Public dividend history (TWSE / Capital Securities announcements)
DIVIDENDS: list[dict[str, Any]] = [
    {
        "ex_date": "2026-09-16",
        "pay_date": "2026-10-15",
        "amount": 1.1,
        "source_capital_gains_pct": 100.0,
        "source_dividends_pct": 0.0,
        "source_equalization_pct": 0.0,
        "note": "已實現資本利得 100%；財產交易所得免列綜所稅（依當次公告）",
    },
    {
        "ex_date": "2026-06-16",
        "pay_date": "2026-07-13",
        "amount": 1.0,
        "source_capital_gains_pct": 100.0,
        "source_dividends_pct": 0.0,
        "source_equalization_pct": 0.0,
        "note": "評價日 2026-05-31；已實現資本利得 100%",
    },
    {
        "ex_date": "2026-03-17",
        "pay_date": "2026-04-14",
        "amount": 0.78,
        "source_capital_gains_pct": None,
        "source_dividends_pct": None,
        "source_equalization_pct": None,
        "note": "來源組成未逐項標註於本評估快照",
    },
    {
        "ex_date": "2025-12-16",
        "pay_date": "2026-01-13",
        "amount": 0.54,
        "source_capital_gains_pct": None,
        "source_dividends_pct": None,
        "source_equalization_pct": None,
        "note": "來源組成未逐項標註於本評估快照",
    },
]

# Holdings snapshot (CMoney / public reports ~2026 mid-year)
HOLDINGS_TOP10: list[dict[str, Any]] = [
    {"name": "富邦金", "weight_pct": 14.47},
    {"name": "國泰金", "weight_pct": 12.67},
    {"name": "中信金", "weight_pct": 10.79},
    {"name": "廣達", "weight_pct": 9.70},
    {"name": "台新新光金", "weight_pct": 7.95},
    {"name": "華碩", "weight_pct": 5.28},
    {"name": "凱基金", "weight_pct": 4.50},
    {"name": "長榮", "weight_pct": 3.75},
    {"name": "聯詠", "weight_pct": 3.57},
    {"name": "瑞昱", "weight_pct": 2.87},
]

FINANCIAL_NAMES = {"富邦金", "國泰金", "中信金", "台新新光金", "凱基金"}

FUND_META = {
    "name": "群益台灣精選高息",
    "ticker": "00919",
    "index": "臺灣指數公司特選臺灣上市上櫃精選高息指數",
    "listed": "2022-10-20",
    "distribution": "季配（3/6/9/12）",
    "aum_billion_twd": 6076.07,
    "beneficiaries_wan": 141.9,
    "expense_mgmt_pct": 0.30,
    "expense_custody_pct": 0.035,
    "has_equalization_reserve": True,
}


def _annualized_vol(close: pd.Series) -> float:
    rets = close.pct_change().dropna()
    if len(rets) < 20:
        return float("nan")
    return float(rets.std(ddof=0) * np.sqrt(252) * 100.0)


def _max_drawdown_pct(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min() * 100.0)


def _period_return_pct(close: pd.Series, days: int) -> Optional[float]:
    if len(close) < 2:
        return None
    if len(close) <= days:
        start = float(close.iloc[0])
    else:
        start = float(close.iloc[-(days + 1)])
    end = float(close.iloc[-1])
    if start <= 0:
        return None
    return round((end / start - 1.0) * 100.0, 2)


def _total_return_with_divs(
    close: pd.Series,
    dividends: list[dict[str, Any]],
    start: Optional[pd.Timestamp] = None,
) -> dict[str, Any]:
    """Approximate total return by reinvesting cash dividends at ex-date close."""
    s = close.copy()
    if start is not None:
        s = s.loc[s.index >= start]
    if s.empty:
        return {"price_return_pct": None, "total_return_pct": None, "divs_collected": 0.0}

    # Units start at 1; cash dividends buy more units at ex-date close
    units = 1.0
    cash_divs = 0.0
    for d in sorted(dividends, key=lambda x: x["ex_date"]):
        ex = pd.Timestamp(d["ex_date"])
        if ex < s.index[0] or ex > s.index[-1]:
            continue
        # use last close on or before ex-date
        px = s.loc[:ex]
        if px.empty:
            continue
        price = float(px.iloc[-1])
        amt = float(d["amount"])
        cash_divs += amt * units
        if price > 0:
            units += (amt * units) / price

    start_px = float(s.iloc[0])
    end_px = float(s.iloc[-1])
    price_ret = (end_px / start_px - 1.0) * 100.0
    total_ret = (units * end_px / start_px - 1.0) * 100.0
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1e-6)
    return {
        "start": str(s.index[0].date()),
        "end": str(s.index[-1].date()),
        "years": round(years, 2),
        "price_return_pct": round(price_ret, 2),
        "total_return_pct": round(total_ret, 2),
        "total_annualized_pct": round(((1 + total_ret / 100) ** (1 / years) - 1) * 100, 2),
        "price_annualized_pct": round(((1 + price_ret / 100) ** (1 / years) - 1) * 100, 2),
        "divs_collected_per_initial_unit": round(cash_divs, 4),
        "ending_units": round(units, 4),
        "max_drawdown_pct": round(_max_drawdown_pct(s), 2),
    }


def _aligned_price_returns(
    series_map: dict[str, pd.Series],
    windows: dict[str, int],
) -> dict[str, dict[str, Optional[float]]]:
    """Price-only returns over common calendar windows (trading days approx)."""
    out: dict[str, dict[str, Optional[float]]] = {}
    for name, s in series_map.items():
        out[name] = {label: _period_return_pct(s, days) for label, days in windows.items()}
        out[name]["vol_pct"] = round(_annualized_vol(s), 2) if len(s) > 20 else None
        out[name]["max_dd_pct"] = round(_max_drawdown_pct(s), 2) if len(s) > 20 else None
        out[name]["last_price"] = round(float(s.iloc[-1]), 4)
        out[name]["as_of"] = str(s.index[-1].date())
    return out


def _equity_curve_normalized(close: pd.Series, n: int = 180) -> list[dict[str, Any]]:
    s = close.iloc[-n:] if len(close) > n else close
    base = float(s.iloc[0])
    return [
        {"date": str(idx.date()), "value": round(float(px) / base * 100.0, 2)}
        for idx, px in s.items()
    ]


def _build_verdict(
    price: float,
    trend: str,
    financial_weight: float,
    recent_div_capital_gains: bool,
    trailing_12m_div: float,
    vs_0050_1y: Optional[float],
    rsi: float,
) -> dict[str, Any]:
    naive_annualized_yield = round(trailing_12m_div / price * 100.0, 2) if price > 0 else None

    cashflow = {
        "verdict": "watch_and_dca",
        "label": "值得關注（現金流用途）",
        "summary": (
            "流動性與配息頻率適合當台股季配現金流工具；"
            "但近期高配息大量來自資本利得，不可把年化殖利率當保證報酬。"
            "宜分批／定投，並用含息總報酬追蹤，而非單看殖利率。"
        ),
    }
    growth = {
        "verdict": "deprioritize",
        "label": "降優先（總報酬用途）",
        "summary": (
            "金融集中約五成，成長市況下長期總報酬通常落後市值型（如 0050）。"
            "若核心目標是資產成長接近大盤，優先關注市值／成長型 ETF。"
        ),
    }

    # Action tier from trend + RSI (no price target)
    if trend in ("StrongUp", "Up") and rsi >= 70:
        action = {
            "tier": "watchlist",
            "label": "關注清單（勿追高）",
            "reason": f"趨勢 `{trend}` 但 RSI={rsi:.1f} 偏熱；熱度高時優先觀察回檔／分批，不宜一次追價。",
        }
    elif trend in ("StrongUp", "Up"):
        action = {
            "tier": "dca_ok",
            "label": "可分批建倉（現金流部位）",
            "reason": f"趨勢 `{trend}`；若目標是現金流，可用定投／回檔分批，部位勿當成成長核心。",
        }
    elif trend == "Range":
        action = {
            "tier": "watchlist",
            "label": "關注清單／區間分批",
            "reason": "區間盤整；適合觀察配息公告與金融股景氣，嚴格區間分批。",
        }
    else:
        action = {
            "tier": "observe",
            "label": "觀望為主",
            "reason": f"趨勢 `{trend}`；現金流需求仍可極小額定投，波段／加碼暫緩。",
        }

    overall = {
        "headline": "值得關注作現金流候選；不宜當追高成長標的",
        "cashflow": cashflow,
        "growth": growth,
        "action": action,
        "flags": [
            f"金融股權重約 {financial_weight:.1f}%（前十大金控合計）",
            "近兩季配息來源以已實現資本利得為主" if recent_div_capital_gains else "配息來源需持續追蹤公告",
            f"近四季累計配息 {trailing_12m_div:.2f} 元；粗估殖利率 {naive_annualized_yield}%（不可外推為可持續報酬）",
            (
                f"近一年價格報酬相對 0050：{vs_0050_1y:+.1f} pct"
                if vs_0050_1y is not None
                else "相對 0050 比較資料不足"
            ),
        ],
    }
    return overall


def build_report(payload: dict[str, Any]) -> str:
    m = payload["meta"]
    v = payload["verdict"]
    levels = payload["levels"]
    cmp_ = payload["comparison"]
    divs = payload["dividends"]
    hold = payload["holdings"]
    tr = payload["total_return_00919"]

    lines = [
        "# 00919 值不值得關注：評估報告",
        "",
        f"**資料日期**：{levels['as_of']} ｜ **現價**：{levels['price']:.2f} ｜ "
        f"**趨勢**：`{levels['trend_state']}` ｜ **裁決**：{v['headline']}",
        "",
        "> 免責：本報告僅供研究參考，非投資建議。",
        "",
        "## 一、雙軌結論",
        "",
        f"| 用途 | 裁決 | 說明 |",
        f"|------|------|------|",
        f"| 現金流 | **{v['cashflow']['label']}** | {v['cashflow']['summary']} |",
        f"| 總報酬成長 | **{v['growth']['label']}** | {v['growth']['summary']} |",
        f"| 現價操作層級 | **{v['action']['label']}** | {v['action']['reason']} |",
        "",
        "### 關鍵旗標",
        "",
    ]
    for f in v["flags"]:
        lines.append(f"- {f}")

    lines += [
        "",
        "## 二、基金快照",
        "",
        f"| 項目 | 內容 |",
        f"|------|------|",
        f"| 名稱 | {m['name']}（{m['ticker']}） |",
        f"| 追蹤指數 | {m['index']} |",
        f"| 上市 | {m['listed']} |",
        f"| 配息 | {m['distribution']} |",
        f"| 規模／受益人次 | 約 {m['aum_billion_twd']:.0f} 億／{m['beneficiaries_wan']} 萬 |",
        f"| 經理＋保管費 | {m['expense_mgmt_pct']}% + {m['expense_custody_pct']}% |",
        f"| 收益平準金 | {'有' if m['has_equalization_reserve'] else '無'} |",
        "",
        "## 三、配息與「假殖利率」",
        "",
        f"近四季累計：**{payload['trailing_4q_div']:.2f} 元**；"
        f"以現價粗估殖利率 **{payload['naive_yield_pct']}%**（單季×4 更不可靠，禁止外推）。",
        "",
        "| 除息日 | 發放日 | 配息 | 資本利得% | 股利% | 平準金% | 備註 |",
        "|--------|--------|------|-----------|-------|---------|------|",
    ]
    for d in divs:
        cg = "—" if d["source_capital_gains_pct"] is None else f"{d['source_capital_gains_pct']:.0f}"
        dv = "—" if d["source_dividends_pct"] is None else f"{d['source_dividends_pct']:.0f}"
        eq = "—" if d["source_equalization_pct"] is None else f"{d['source_equalization_pct']:.0f}"
        lines.append(
            f"| {d['ex_date']} | {d['pay_date']} | {d['amount']} | {cg} | {dv} | {eq} | {d['note']} |"
        )

    lines += [
        "",
        "重點：配息是資產轉成現金；淨值會同步扣減。真實賺賠看**含息總報酬**與填息能力。",
        "",
        f"- 自上市以來（價格＋再投資配息粗估）：總報酬 **{tr['total_return_pct']}%**"
        f"（年化 {tr['total_annualized_pct']}%）；純價格 **{tr['price_return_pct']}%**"
        f"；最大回撤 **{tr['max_drawdown_pct']}%**。",
        "",
        "## 四、持股集中度",
        "",
        f"前十大合計約 **{hold['top10_weight_pct']:.1f}%**；"
        f"前十大中金融股約 **{hold['financial_in_top10_pct']:.1f}%**。",
        "",
        "| 成分 | 權重% |",
        "|------|------|",
    ]
    for h in hold["top10"]:
        tag = "（金融）" if h["name"] in FINANCIAL_NAMES else ""
        lines.append(f"| {h['name']}{tag} | {h['weight_pct']:.2f} |")

    lines += [
        "",
        "解讀：00919 近期較像「金融＋高息電子」主題組合，利率／壽險評價／金融景氣敏感度高。",
        "",
        "## 五、總報酬對照（價格報酬）",
        "",
        "| 標的 | 1M | 3M | 6M | 1Y | 年化波動 | 最大回撤 |",
        "|------|----|----|----|----|----------|----------|",
    ]
    for name in ("00919", "0050", "00878"):
        r = cmp_[name]
        lines.append(
            f"| {name} | {r.get('1M')}% | {r.get('3M')}% | {r.get('6M')}% | {r.get('1Y')}% | "
            f"{r.get('vol_pct')}% | {r.get('max_dd_pct')}% |"
        )

    lines += [
        "",
        "> 上表為**價格報酬**（未加回配息）。高息 ETF 的總報酬通常高於價格報酬；"
        "與 0050 比較時仍建議同時看含息曲線。",
        "",
        "## 六、技術狀態（輔助，非進出場喊單）",
        "",
        f"| 指標 | 數值 |",
        f"|------|------|",
        f"| MA20 / MA60 / MA120 | {levels['ma20']:.2f} / {levels['ma60']:.2f} / {levels.get('ma120') or 'n/a'} |",
        f"| RSI(14) | {levels['rsi14']:.1f} |",
        f"| ATR(14) | {levels['atr14']:.3f} |",
        f"| 近端支撐／壓力 | {levels['support_near']:.2f} / {levels['resistance_near']:.2f} |",
        f"| 回檔買參考 (MA20) | {levels['swing_buy_pullback']:.2f} |",
        f"| 訊號 | {', '.join(levels['signals']) if levels['signals'] else '無'} |",
        "",
        "## 七、風險提醒",
        "",
        "- 高年化殖利率若主要來自資本利得／平準金，配息下滑與淨值震盪風險並存。",
        "- 金融股權重高時，升息尾聲、利差、資本市場成交量變化都會放大波動。",
        "- 換股後風格可能漂移；「高股息」名稱不變，內涵會變。",
        "- 公開行情／持股／配息來源以投信與證交所公告為準。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching 00919 / 0050 / 00878...")
    bars_919 = fetch_daily(
        ticker="00919.TW",
        period="5y",
        cache_path=DATA_DIR / "00919_daily.csv",
        use_cache=False,
    )
    bars_50 = fetch_daily(
        ticker="0050.TW",
        period="5y",
        cache_path=DATA_DIR / "0050_daily.csv",
        use_cache=False,
    )
    bars_878 = fetch_daily(
        ticker="00878.TW",
        period="5y",
        cache_path=DATA_DIR / "00878_daily.csv",
        use_cache=False,
    )

    # Align comparison to 00919 listing window
    start_919 = bars_919.index[0]
    c919 = bars_919["Close"]
    c50 = bars_50["Close"].loc[start_919:]
    c878 = bars_878["Close"].loc[start_919:]

    windows = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}
    comparison = _aligned_price_returns(
        {"00919": c919, "0050": c50, "00878": c878},
        windows,
    )

    total_ret = _total_return_with_divs(c919, DIVIDENDS)

    financial_w = sum(h["weight_pct"] for h in HOLDINGS_TOP10 if h["name"] in FINANCIAL_NAMES)
    top10_w = sum(h["weight_pct"] for h in HOLDINGS_TOP10)
    trailing_4q = sum(d["amount"] for d in DIVIDENDS[:4])
    price = float(c919.iloc[-1])
    naive_yield = round(trailing_4q / price * 100.0, 2)

    vs_0050_1y = None
    if comparison["00919"].get("1Y") is not None and comparison["0050"].get("1Y") is not None:
        vs_0050_1y = round(comparison["00919"]["1Y"] - comparison["0050"]["1Y"], 2)

    print("Computing trend / levels...")
    enriched = attach_trend_state(bars_919)
    levels = compute_trade_levels(enriched)
    levels_d = levels.to_dict()

    recent_cg = all(
        d.get("source_capital_gains_pct") == 100.0 for d in DIVIDENDS[:2]
    )

    verdict = _build_verdict(
        price=price,
        trend=levels.trend_state,
        financial_weight=financial_w,
        recent_div_capital_gains=recent_cg,
        trailing_12m_div=trailing_4q,
        vs_0050_1y=vs_0050_1y,
        rsi=levels.rsi14,
    )

    # Normalized equity for chart (common index dates)
    common = c919.index.intersection(c50.index).intersection(c878.index)
    common = common[-180:] if len(common) > 180 else common
    equity_compare = {
        "dates": [str(d.date()) for d in common],
        "00919": [
            round(float(c919.loc[d]) / float(c919.loc[common[0]]) * 100, 2) for d in common
        ],
        "0050": [
            round(float(c50.loc[d]) / float(c50.loc[common[0]]) * 100, 2) for d in common
        ],
        "00878": [
            round(float(c878.loc[d]) / float(c878.loc[common[0]]) * 100, 2) for d in common
        ],
    }

    payload = {
        "meta": FUND_META,
        "as_of": levels.as_of,
        "price": round(price, 4),
        "dividends": DIVIDENDS,
        "trailing_4q_div": round(trailing_4q, 2),
        "naive_yield_pct": naive_yield,
        "holdings": {
            "top10": HOLDINGS_TOP10,
            "top10_weight_pct": round(top10_w, 2),
            "financial_in_top10_pct": round(financial_w, 2),
            "source_note": "CMoney / public holdings snapshot; weights drift after rebalance",
        },
        "comparison": comparison,
        "total_return_00919": total_ret,
        "levels": levels_d,
        "verdict": verdict,
        "equity_compare": equity_compare,
        "disclaimer": "For research only. Not investment advice.",
    }

    json_path = OUTPUT_DIR / "00919_watch_latest.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(payload)
    report_path = REPORTS_DIR / "00919_watch_eval.md"
    report_path.write_text(report, encoding="utf-8")

    # Compact canvas payload (watch eval canvas)
    canvas_payload = {
        "as_of": payload["as_of"],
        "price": payload["price"],
        "naive_yield_pct": naive_yield,
        "trailing_4q_div": trailing_4q,
        "financial_pct": round(financial_w, 2),
        "top10_pct": round(top10_w, 2),
        "verdict": verdict,
        "comparison": comparison,
        "total_return": total_ret,
        "levels": {
            "trend_state": levels.trend_state,
            "rsi14": levels.rsi14,
            "ma20": levels.ma20,
            "ma60": levels.ma60,
            "support_near": levels.support_near,
            "resistance_near": levels.resistance_near,
        },
        "dividends": [
            {
                "ex_date": d["ex_date"],
                "amount": d["amount"],
                "cg": d["source_capital_gains_pct"],
            }
            for d in DIVIDENDS
        ],
        "holdings": HOLDINGS_TOP10,
        "equity_compare": equity_compare,
        "meta": FUND_META,
    }
    (OUTPUT_DIR / "00919_watch_canvas_payload.json").write_text(
        json.dumps(canvas_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote {json_path}")
    print(f"Wrote {report_path}")
    print(f"Verdict: {verdict['headline']}")
    print(f"Action: {verdict['action']['label']} | trend={levels.trend_state} RSI={levels.rsi14}")


if __name__ == "__main__":
    main()
