"""Fundamental snapshot and environment filter for 0050."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

import pandas as pd


@dataclass
class FundamentalSnapshot:
    as_of: str
    pe_ratio: Optional[float]
    annualized_volatility_pct: Optional[float]
    cash_dividend_yield_pct: Optional[float]
    tsmc_weight_pct: Optional[float]
    premium_pct: Optional[float]
    nav: Optional[float]
    market_price: float
    pe_bias: str  # bullish / neutral / cautious
    vol_bias: str
    premium_bias: str
    overall_bias: str  # accumulate / neutral / defensive
    position_cap_pct: float  # 100 or 70
    notes: str
    source_pe: str
    source_tsmc_weight: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Manual / semi-auto defaults from Yuanta / public sources (update when refreshing)
# P/E ~29.15 (Yuanta ETF Characteristic around 2026/08), TSMC weight ~58-61%
DEFAULT_PE = 29.15
DEFAULT_PE_AS_OF = "2026-08-31"
DEFAULT_TSMC_WEIGHT = 60.0
DEFAULT_DIV_YIELD = 1.5
# Rough 3y PE percentile proxy without long PE history: treat 22=low, 35=high
PE_P60 = 28.0
PE_P80 = 32.0


def realized_volatility_pct(close: pd.Series, window: int = 252) -> float:
    """Annualized realized vol from daily log returns."""
    rets = close.pct_change().dropna()
    if len(rets) < 60:
        return float("nan")
    # Use last ~1y if available
    sample = rets.iloc[-window:] if len(rets) >= window else rets
    return float(sample.std(ddof=1) * (252**0.5) * 100.0)


def tsmc_trend_ok(tsmc: Optional[pd.DataFrame]) -> bool:
    """True if TSMC close above its MA60 (or unknown -> True)."""
    if tsmc is None or tsmc.empty or len(tsmc) < 60:
        return True
    close = tsmc["Close"]
    ma60 = close.rolling(60).mean().iloc[-1]
    return bool(close.iloc[-1] >= ma60)


def build_fundamental_snapshot(
    market_price: float,
    close_series: pd.Series,
    premium_pct: Optional[float] = None,
    nav: Optional[float] = None,
    pe_ratio: float = DEFAULT_PE,
    pe_as_of: str = DEFAULT_PE_AS_OF,
    tsmc_weight_pct: float = DEFAULT_TSMC_WEIGHT,
    div_yield: float = DEFAULT_DIV_YIELD,
    tsmc_df: Optional[pd.DataFrame] = None,
) -> FundamentalSnapshot:
    vol = realized_volatility_pct(close_series)
    if pe_ratio < PE_P60:
        pe_bias = "bullish"
    elif pe_ratio > PE_P80:
        pe_bias = "cautious"
    else:
        pe_bias = "neutral"

    if pd.isna(vol):
        vol_bias = "neutral"
        position_cap = 100.0
    elif vol < 25.0:
        vol_bias = "bullish"
        position_cap = 100.0
    elif vol > 30.0:
        vol_bias = "cautious"
        position_cap = 70.0
    else:
        vol_bias = "neutral"
        position_cap = 100.0

    if premium_pct is None:
        premium_bias = "neutral"
    elif premium_pct < -0.3:
        premium_bias = "bullish"  # discount helps add
    elif premium_pct > 0.5:
        premium_bias = "cautious"
    else:
        premium_bias = "neutral"

    tsmc_ok = tsmc_trend_ok(tsmc_df)
    concentration_note = ""
    if tsmc_weight_pct >= 55.0 and not tsmc_ok:
        concentration_note = "TSMC below MA60 — swing book defensive only. "
        pe_bias = "cautious"

    scores = {"bullish": 1, "neutral": 0, "cautious": -1}
    score = scores[pe_bias] + scores[vol_bias] + scores[premium_bias]
    if not tsmc_ok and tsmc_weight_pct >= 55.0:
        score -= 1

    if score >= 2:
        overall = "accumulate"
    elif score <= -1:
        overall = "defensive"
    else:
        overall = "neutral"

    notes = (
        f"PE as of {pe_as_of} (Yuanta-style weighted estimate). "
        f"{concentration_note}"
        "Fundamentals set environment for DCA add-ons, not day entries."
    )

    return FundamentalSnapshot(
        as_of=str(date.today()),
        pe_ratio=round(pe_ratio, 2),
        annualized_volatility_pct=None if pd.isna(vol) else round(vol, 2),
        cash_dividend_yield_pct=div_yield,
        tsmc_weight_pct=tsmc_weight_pct,
        premium_pct=None if premium_pct is None else round(premium_pct, 4),
        nav=nav,
        market_price=round(market_price, 4),
        pe_bias=pe_bias,
        vol_bias=vol_bias,
        premium_bias=premium_bias,
        overall_bias=overall,
        position_cap_pct=position_cap,
        notes=notes,
        source_pe=f"Yuanta/manual ({pe_as_of})",
        source_tsmc_weight="public holdings ~60% (manual)",
    )
