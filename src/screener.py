"""Fundamental + technical screener over constituent ETFs."""

from __future__ import annotations

import time
from typing import Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from src.catalog import apply_catalog_to_universe
from src.fetch_0050 import fetch_daily
from src.fetch_holdings import union_universe
from src.screener_config import ScreenerConfig
from src.signals import attach_trend_state, compute_trade_levels
from src.tech_filters import tech_hits, tech_passes

STOCK_CACHE_DIR_NAME = "stocks"


def _yf_symbol(ticker: str, market: str = "TW") -> str:
    return f"{str(ticker).zfill(4)}.{market}"


def _load_prices(ticker: str, cfg: ScreenerConfig, cache_dir) -> Optional[pd.DataFrame]:
    """Listed names use .TW; OTC names fall back to .TWO."""
    ticker = str(ticker).zfill(4)
    attempts = (
        ("TW", cache_dir / f"{ticker}_daily.csv"),
        ("TWO", cache_dir / f"{ticker}_two_daily.csv"),
    )
    for market, cache_path in attempts:
        sym = _yf_symbol(ticker, market)
        try:
            px = fetch_daily(
                ticker=sym,
                period=cfg.period,
                cache_path=cache_path,
                use_cache=cfg.use_cache_prices,
            )
        except Exception:
            px = None
        if px is not None and len(px) >= 60:
            return px
    print(f"  skip {ticker}: price fetch failed")
    return None


def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    """Pull PE / dividend yield from yfinance; OTC names fall back to .TWO."""
    info: dict[str, Any] = {}
    for market in ("TW", "TWO"):
        try:
            info = yf.Ticker(_yf_symbol(ticker, market)).info or {}
        except Exception:
            info = {}
        if info.get("trailingPE") is not None or info.get("dividendYield") is not None or info.get("shortName"):
            break

    pe = info.get("trailingPE")
    if pe is None:
        pe = info.get("forwardPE")
    yield_v = info.get("dividendYield")
    if yield_v is None:
        yield_v = info.get("trailingAnnualDividendYield")
    # yfinance sometimes returns yield as fraction, sometimes as percent-like
    if yield_v is not None:
        try:
            yield_v = float(yield_v)
            if yield_v > 1.0:  # e.g. 5.2 meaning 5.2%
                yield_v = yield_v / 100.0
            # TW cash yields > 20% are almost always bad Yahoo data
            if yield_v < 0 or yield_v > 0.20:
                yield_v = None
        except (TypeError, ValueError):
            yield_v = None

    pe_f: Optional[float]
    try:
        pe_f = float(pe) if pe is not None and not (isinstance(pe, float) and np.isnan(pe)) else None
        if pe_f is not None and (pe_f <= 0 or pe_f > 500):
            pe_f = None
    except (TypeError, ValueError):
        pe_f = None

    incomplete = pe_f is None or yield_v is None
    return {
        "trailing_pe": pe_f,
        "dividend_yield": yield_v,
        "fund_incomplete": incomplete,
        "name_yf": info.get("shortName") or info.get("longName"),
    }


def _score_row(
    pe: Optional[float],
    div_yield: Optional[float],
    pe_median: Optional[float],
    cfg: ScreenerConfig,
) -> tuple[float, float]:
    """Return (long_score, short_score). Higher is stronger for that side."""
    long_s = 0.0
    short_s = 0.0

    if div_yield is not None:
        if div_yield >= cfg.min_yield:
            long_s += 2.0 + min(div_yield / max(cfg.min_yield, 1e-6), 3.0)
        else:
            short_s += 1.0 + (cfg.min_yield - div_yield) * 10.0
        if div_yield < cfg.min_yield * 0.5:
            short_s += 1.0

    if pe is not None:
        if pe <= cfg.max_pe:
            long_s += 2.0 + max(0.0, (cfg.max_pe - pe) / max(cfg.max_pe, 1.0)) * 2.0
        if pe >= cfg.min_pe_short:
            short_s += 2.0 + min((pe - cfg.min_pe_short) / max(cfg.min_pe_short, 1.0), 2.0)
        if pe_median and pe_median > 0:
            if pe <= pe_median * cfg.pe_vs_median_max:
                long_s += 1.5
            if pe >= pe_median * cfg.pe_vs_median_min_short:
                short_s += 1.5

    return round(long_s, 3), round(short_s, 3)


def _label_candidate(
    long_score: float,
    short_score: float,
    trend: str,
    row: Any,
    pe: Optional[float],
    div_yield: Optional[float],
    fund_incomplete: bool,
    cfg: ScreenerConfig,
) -> str:
    long_trend_ok = trend in cfg.long_trends
    short_trend_ok = trend in cfg.short_trends

    long_fund_ok = True
    short_fund_ok = True
    if not fund_incomplete:
        long_fund_ok = (div_yield is None or div_yield >= cfg.min_yield) and (
            pe is None or pe <= cfg.max_pe
        )
        short_fund_ok = (pe is not None and pe >= cfg.min_pe_short) or (
            div_yield is not None and div_yield < cfg.min_yield * 0.75
        )
    else:
        # Incomplete fundamentals: allow watch via trend/RSI only (weaker)
        long_fund_ok = False
        short_fund_ok = False

    long_ok = long_fund_ok and long_trend_ok and tech_passes("long", row, cfg) and long_score >= 2.0
    short_ok = short_fund_ok and short_trend_ok and tech_passes("short", row, cfg) and short_score >= 2.0

    if long_ok and short_ok:
        return "long_candidate" if long_score >= short_score else "short_candidate"
    if long_ok:
        return "long_candidate"
    if short_ok:
        return "short_candidate"
    if long_trend_ok or short_trend_ok or fund_incomplete:
        return "watch"
    return "skip"


def analyze_ticker(
    ticker: str,
    meta: dict[str, Any],
    cfg: ScreenerConfig,
    root_data_dir,
) -> Optional[dict[str, Any]]:
    cache_dir = root_data_dir / STOCK_CACHE_DIR_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    px = _load_prices(ticker, cfg, cache_dir)
    if px is None:
        return None

    enriched = attach_trend_state(px)
    levels = compute_trade_levels(
        enriched,
        stop_mult=cfg.atr_stop,
        target1_mult=cfg.atr_target1,
        target2_mult=cfg.atr_target2,
        short_stop_mult=cfg.atr_stop_short,
        short_target1_mult=cfg.atr_target1_short,
        short_target2_mult=cfg.atr_target2_short,
    )
    fund = fetch_fundamentals(ticker)
    name = meta.get("name") or fund.get("name_yf") or ticker

    return {
        "ticker": ticker,
        "name": name,
        "etf_membership": meta.get("etf_membership"),
        "in_0050": bool(meta.get("in_0050")),
        "in_00919": bool(meta.get("in_00919")),
        "weight_0050": meta.get("weight_0050"),
        "weight_00919": meta.get("weight_00919"),
        "weights": meta.get("weights") if isinstance(meta.get("weights"), dict) else {},
        "member_etfs": list(meta.get("member_etfs") or []),
        "weight_max": meta.get("weight_max"),
        "as_of": levels.as_of,
        "price": levels.price,
        "trend_state": levels.trend_state,
        "rsi14": levels.rsi14,
        "atr14": levels.atr14,
        "ma5": levels.ma5,
        "ma10": levels.ma10,
        "ma20": levels.ma20,
        "ma30": levels.ma30,
        "ma60": levels.ma60,
        "ma90": levels.ma90,
        "ma120": levels.ma120,
        "macd": levels.macd,
        "macd_signal": levels.macd_signal,
        "macd_hist": levels.macd_hist,
        "macd_hist_prev": levels.macd_hist_prev,
        "k9": levels.k9,
        "d9": levels.d9,
        "bb_lower": levels.bb_lower,
        "bb_mid": levels.bb_mid,
        "bb_upper": levels.bb_upper,
        "vol_ratio": levels.vol_ratio,
        "high_20": levels.high_20,
        "low_20": levels.low_20,
        "trailing_pe": fund["trailing_pe"],
        "dividend_yield": fund["dividend_yield"],
        "fund_incomplete": fund["fund_incomplete"],
        "long_entry": levels.swing_buy_pullback,
        "long_stop": levels.stop_ref,
        "long_target1": levels.target1,
        "long_target2": levels.target2,
        "short_entry": levels.short_entry_ref,
        "short_stop": levels.short_stop_ref,
        "short_target1": levels.short_target1,
        "short_target2": levels.short_target2,
        "support_near": levels.support_near,
        "resistance_near": levels.resistance_near,
        "signals": ",".join(levels.signals),
        "swing_long_allowed": levels.swing_long_allowed,
        "swing_short_allowed": levels.swing_short_allowed,
        "custom": bool(meta.get("custom")),
        "category_ids": list(meta.get("category_ids") or []),
        "category_names": list(meta.get("category_names") or []),
    }


def apply_scores(df: pd.DataFrame, cfg: ScreenerConfig) -> pd.DataFrame:
    """Assign long/short scores and labels in place-friendly copy."""
    out = df.copy()
    pe_median = (
        float(out["trailing_pe"].dropna().median()) if out["trailing_pe"].notna().any() else None
    )
    long_scores = []
    short_scores = []
    long_hits = []
    short_hits = []
    labels = []
    conflict = []
    for _, r in out.iterrows():
        ls, ss = _score_row(r["trailing_pe"], r["dividend_yield"], pe_median, cfg)
        hit_long, _ = tech_hits("long", r, cfg)
        hit_short, _ = tech_hits("short", r, cfg)
        ls += hit_long
        ss += hit_short
        long_scores.append(ls)
        short_scores.append(ss)
        long_hits.append(hit_long)
        short_hits.append(hit_short)
        label = _label_candidate(
            ls,
            ss,
            str(r["trend_state"]),
            r,
            r["trailing_pe"],
            r["dividend_yield"],
            bool(r["fund_incomplete"]),
            cfg,
        )
        labels.append(label)
        if ls >= 2.0 and ss >= 2.0 and label in ("long_candidate", "short_candidate"):
            conflict.append("conflict")
        else:
            conflict.append("")
    out["pe_median_universe"] = pe_median
    out["long_score"] = long_scores
    out["short_score"] = short_scores
    out["tech_long_hits"] = long_hits
    out["tech_short_hits"] = short_hits
    out["label"] = labels
    out["note"] = conflict
    return out.sort_values(
        ["label", "long_score", "short_score"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def run_screener(cfg: ScreenerConfig, root, progress_cb=None) -> pd.DataFrame:
    """Build universe, score each name, assign labels. Returns full result DataFrame."""
    universe = union_universe(
        universe=cfg.universe,
        use_cache=cfg.use_cache_holdings,
        min_weight=cfg.min_weight,
    )
    universe = apply_catalog_to_universe(universe)
    if cfg.universe == "custom" and "custom" in universe.columns:
        universe = universe[universe["custom"].astype(bool)].reset_index(drop=True)
    print(f"Universe size: {len(universe)} (universe={cfg.universe})")

    data_dir = root / "data"
    rows: list[dict[str, Any]] = []
    total = len(universe)
    for i, row in universe.iterrows():
        ticker = str(row["ticker"]).zfill(4)
        name = str(row.get("name", "") or "")
        print(f"[{i + 1}/{total}] {ticker} {name}")
        if progress_cb:
            progress_cb(
                {
                    "current": int(i) + 1,
                    "total": total,
                    "ticker": ticker,
                    "name": name,
                    "message": f"{ticker} {name}".strip(),
                }
            )
        meta = row.to_dict()
        analyzed = analyze_ticker(ticker, meta, cfg, data_dir)
        if analyzed is None:
            continue
        rows.append(analyzed)
        if cfg.sleep_sec > 0:
            time.sleep(cfg.sleep_sec)

    if not rows:
        raise RuntimeError("Screener produced no rows")

    return apply_scores(pd.DataFrame(rows), cfg)


def top_slices(df: pd.DataFrame, top_n: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    longs = df[df["label"] == "long_candidate"].sort_values("long_score", ascending=False).head(top_n)
    shorts = df[df["label"] == "short_candidate"].sort_values("short_score", ascending=False).head(top_n)
    watch = df[df["label"] == "watch"].head(top_n)
    return longs, shorts, watch
