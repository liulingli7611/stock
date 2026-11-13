"""Fundamental snapshot and environment filter for 00919 (高股息／金融集中)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

import pandas as pd

from src.fundamentals import realized_volatility_pct


@dataclass
class FundamentalSnapshot00919:
    as_of: str
    pe_ratio: Optional[float]
    annualized_volatility_pct: Optional[float]
    cash_dividend_yield_pct: Optional[float]
    financial_weight_pct: Optional[float]
    premium_pct: Optional[float]
    nav: Optional[float]
    market_price: float
    pe_bias: str
    vol_bias: str
    premium_bias: str
    financial_bias: str
    overall_bias: str
    position_cap_pct: float
    notes: str
    source_pe: str
    source_financial_weight: str
    # Alias field so sync/canvas can reuse tsmc_weight_pct key shape if needed
    tsmc_weight_pct: Optional[float] = None  # unused; kept None for schema parity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Manual holdings snapshot (update on rebalance). Top-10 financials ~50%.
DEFAULT_FINANCIAL_WEIGHT = 50.4
DEFAULT_FINANCIAL_AS_OF = "2026-mid"
# Trailing-4Q cash div / price (naive); capital-gains heavy — not sustainable yield.
DEFAULT_DIV_YIELD = 10.65
# High-div ETFs: PE less meaningful; leave None unless published.
DEFAULT_PE: Optional[float] = None


def financial_proxy_trend_ok(proxy: Optional[pd.DataFrame]) -> bool:
    """True if financial proxy (e.g. 2881 富邦金) close above MA60, or unknown."""
    if proxy is None or proxy.empty or len(proxy) < 60:
        return True
    close = proxy["Close"]
    ma60 = close.rolling(60).mean().iloc[-1]
    return bool(close.iloc[-1] >= ma60)


def build_fundamental_snapshot_00919(
    market_price: float,
    close_series: pd.Series,
    premium_pct: Optional[float] = None,
    nav: Optional[float] = None,
    pe_ratio: Optional[float] = DEFAULT_PE,
    financial_weight_pct: float = DEFAULT_FINANCIAL_WEIGHT,
    financial_as_of: str = DEFAULT_FINANCIAL_AS_OF,
    div_yield: float = DEFAULT_DIV_YIELD,
    financial_proxy_df: Optional[pd.DataFrame] = None,
) -> FundamentalSnapshot00919:
    vol = realized_volatility_pct(close_series)

    # PE optional for high-div ETF
    if pe_ratio is None:
        pe_bias = "neutral"
    elif pe_ratio < 12:
        pe_bias = "bullish"
    elif pe_ratio > 18:
        pe_bias = "cautious"
    else:
        pe_bias = "neutral"

    # 00919 typically lower vol than 0050; thresholds slightly tighter
    if pd.isna(vol):
        vol_bias = "neutral"
        position_cap = 100.0
    elif vol < 18.0:
        vol_bias = "bullish"
        position_cap = 100.0
    elif vol > 25.0:
        vol_bias = "cautious"
        position_cap = 70.0
    else:
        vol_bias = "neutral"
        position_cap = 100.0

    if premium_pct is None:
        premium_bias = "neutral"
    elif premium_pct < -0.3:
        premium_bias = "bullish"
    elif premium_pct > 0.5:
        premium_bias = "cautious"
    else:
        premium_bias = "neutral"

    fin_ok = financial_proxy_trend_ok(financial_proxy_df)
    concentration_note = ""
    if financial_weight_pct >= 45.0:
        if fin_ok:
            financial_bias = "neutral"
            concentration_note = (
                f"金融權重約 {financial_weight_pct:.1f}%（{financial_as_of}）；"
                "代理標的（富邦金）在 MA60 上。"
            )
        else:
            financial_bias = "cautious"
            concentration_note = (
                f"金融權重約 {financial_weight_pct:.1f}% 且代理標的跌破 MA60 — "
                "波段偏向防守。"
            )
            pe_bias = "cautious"
    else:
        financial_bias = "bullish"

    scores = {"bullish": 1, "neutral": 0, "cautious": -1}
    score = (
        scores[pe_bias]
        + scores[vol_bias]
        + scores[premium_bias]
        + scores[financial_bias]
    )
    # Naive yield >12% often means capital-gains distribution — mild caution
    if div_yield >= 12.0:
        score -= 1
        concentration_note += " 粗估殖利率偏高，配息來源需核對資本利得／平準金。"

    if score >= 2:
        overall = "accumulate"
    elif score <= -1:
        overall = "defensive"
    else:
        overall = "neutral"

    notes = (
        f"{concentration_note} "
        "基本面濾網只定中長期加碼環境，不單獨觸發當日進出。"
        "00919 配息常含資本利得；總報酬優於單看殖利率。"
    )

    return FundamentalSnapshot00919(
        as_of=str(date.today()),
        pe_ratio=None if pe_ratio is None else round(pe_ratio, 2),
        annualized_volatility_pct=None if pd.isna(vol) else round(vol, 2),
        cash_dividend_yield_pct=round(div_yield, 2),
        financial_weight_pct=round(financial_weight_pct, 2),
        premium_pct=None if premium_pct is None else round(premium_pct, 4),
        nav=nav,
        market_price=round(market_price, 4),
        pe_bias=pe_bias,
        vol_bias=vol_bias,
        premium_bias=premium_bias,
        financial_bias=financial_bias,
        overall_bias=overall,
        position_cap_pct=position_cap,
        notes=notes.strip(),
        source_pe="n/a (high-div ETF; PE not primary)",
        source_financial_weight=f"public holdings ~{financial_weight_pct:.0f}% ({financial_as_of})",
        tsmc_weight_pct=None,
    )
