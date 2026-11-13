"""Technical indicators, trend state machine, price zones and trade levels."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            (df["High"] - df["Low"]).abs(),
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def stochastic_kd(
    df: pd.DataFrame, k_window: int = 9, d_window: int = 3
) -> tuple[pd.Series, pd.Series]:
    low_n = df["Low"].rolling(k_window, min_periods=k_window).min()
    high_n = df["High"].rolling(k_window, min_periods=k_window).max()
    span = (high_n - low_n).replace(0, np.nan)
    k = 100 * (df["Close"] - low_n) / span
    d = k.rolling(d_window, min_periods=d_window).mean()
    return k, d


def bollinger(
    series: pd.Series, window: int = 20, n_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, window)
    std = series.rolling(window, min_periods=window).std(ddof=0)
    upper = mid + n_std * std
    lower = mid - n_std * std
    return lower, mid, upper


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    ohlc = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    weekly = df.resample("W-FRI").agg(ohlc).dropna(subset=["Close"])
    return weekly


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["Close"]
    out["MA5"] = sma(c, 5)
    out["MA10"] = sma(c, 10)
    out["MA20"] = sma(c, 20)
    out["MA30"] = sma(c, 30)
    out["MA60"] = sma(c, 60)
    out["MA90"] = sma(c, 90)
    out["MA120"] = sma(c, 120)
    out["RSI14"] = rsi(c, 14)
    macd_line, signal_line, hist = macd(c)
    out["MACD"] = macd_line
    out["MACD_signal"] = signal_line
    out["MACD_hist"] = hist
    bb_l, bb_m, bb_u = bollinger(c)
    out["BB_lower"] = bb_l
    out["BB_mid"] = bb_m
    out["BB_upper"] = bb_u
    out["ATR14"] = atr(out, 14)
    k9, d9 = stochastic_kd(out)
    out["K9"] = k9
    out["D9"] = d9
    out["VOL_MA20"] = out["Volume"].rolling(20, min_periods=20).mean()
    out["high_20"] = out["High"].rolling(20, min_periods=20).max()
    out["low_20"] = out["Low"].rolling(20, min_periods=20).min()
    out["low_60"] = out["Low"].rolling(60, min_periods=60).min()
    out["ret_20"] = c.pct_change(20)
    return out


def classify_trend(row: pd.Series, weekly_close: float, weekly_ma20: float) -> str:
    close = float(row["Close"])
    ma20 = float(row["MA20"])
    ma60 = float(row["MA60"])
    bb_mid = float(row["BB_mid"])
    macd_h = float(row["MACD_hist"])
    macd_v = float(row["MACD"])

    week_ok = weekly_close >= weekly_ma20
    if np.isnan(ma20) or np.isnan(ma60) or np.isnan(bb_mid):
        return "Range"

    # Down: below MA60 or weekly trend broken
    if close < ma60 or not week_ok:
        return "Down"

    if close > ma20 > ma60 and week_ok:
        return "StrongUp"
    if close > ma60 and week_ok:
        # Distinguish quiet range vs directional Up
        near_mid = abs(close - bb_mid) / close < 0.015
        macd_quiet = abs(macd_h) < (close * 0.0008) and abs(macd_v) < (close * 0.002)
        if near_mid and macd_quiet and not (close > ma20 > ma60):
            return "Range"
        return "Up"

    return "Range"


def attach_trend_state(df: pd.DataFrame) -> pd.DataFrame:
    weekly = to_weekly(df[["Open", "High", "Low", "Close", "Volume"]])
    weekly["MA20"] = sma(weekly["Close"], 20)
    out = enrich_indicators(df)
    states = []
    for idx, row in out.iterrows():
        # last weekly bar on or before this date
        w = weekly.loc[:idx]
        if w.empty or pd.isna(w["MA20"].iloc[-1]):
            states.append("Range")
            continue
        states.append(
            classify_trend(row, float(w["Close"].iloc[-1]), float(w["MA20"].iloc[-1]))
        )
    out["trend_state"] = states
    return out


@dataclass
class TradeLevels:
    as_of: str
    price: float
    trend_state: str
    ma5: float
    ma10: float
    ma20: float
    ma30: Optional[float]
    ma60: float
    ma90: Optional[float]
    ma120: Optional[float]
    rsi14: float
    macd: float
    macd_signal: float
    macd_hist: float
    atr14: float
    bb_lower: float
    bb_mid: float
    bb_upper: float
    vol_ratio: Optional[float]
    support_near: float
    support_mid: float
    resistance_near: float
    stop_ref: float
    swing_buy_pullback: float
    swing_buy_breakout: float
    target1: float
    target2: float
    zone_a: float
    zone_b: float
    zone_c_trigger: str
    swing_long_allowed: bool
    position_size_hint: str
    signals: list[str]
    # Short-side reference levels (optional; filled when stop/target mults provided)
    short_entry_ref: Optional[float] = None
    short_stop_ref: Optional[float] = None
    short_target1: Optional[float] = None
    short_target2: Optional[float] = None
    swing_short_allowed: Optional[bool] = None
    k9: Optional[float] = None
    d9: Optional[float] = None
    high_20: Optional[float] = None
    low_20: Optional[float] = None
    macd_hist_prev: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_trade_levels(
    df: pd.DataFrame,
    stop_mult: float = 1.5,
    target1_mult: float = 1.5,
    target2_mult: float = 2.5,
    short_stop_mult: Optional[float] = None,
    short_target1_mult: Optional[float] = None,
    short_target2_mult: Optional[float] = None,
) -> TradeLevels:
    if "trend_state" not in df.columns:
        df = attach_trend_state(df)
    row = df.iloc[-1]
    price = float(row["Close"])
    atr_v = float(row["ATR14"])
    ma5 = float(row["MA5"])
    ma10 = float(row["MA10"])
    ma20 = float(row["MA20"])
    ma30 = float(row["MA30"]) if "MA30" in row and not pd.isna(row["MA30"]) else float("nan")
    ma60 = float(row["MA60"])
    ma90 = float(row["MA90"]) if "MA90" in row and not pd.isna(row["MA90"]) else float("nan")
    ma120 = float(row["MA120"]) if not pd.isna(row["MA120"]) else float("nan")
    bb_l = float(row["BB_lower"])
    bb_m = float(row["BB_mid"])
    bb_u = float(row["BB_upper"])
    low20 = float(row["low_20"])
    high20 = float(row["high_20"])
    rsi_v = float(row["RSI14"])
    state = str(row["trend_state"])
    vol_ma = row["VOL_MA20"]
    vol_ratio = (
        float(row["Volume"] / vol_ma) if vol_ma and not pd.isna(vol_ma) and vol_ma > 0 else None
    )

    support_near = max(x for x in (ma20, bb_l, low20) if not np.isnan(x))
    support_mid = ma60 - 0.5 * atr_v if not np.isnan(ma60) else price - atr_v
    resistance_near = min(x for x in (high20, bb_u) if not np.isnan(x))

    # Reference entry for targets: prefer pullback level if in uptrend else price
    entry_ref = min(price, ma20) if state in ("StrongUp", "Up") else price
    stop_ref = entry_ref - stop_mult * atr_v
    target1 = entry_ref + target1_mult * atr_v
    target2_atr = entry_ref + target2_mult * atr_v
    # Default 2.5× keeps prior behaviour (prefer 20d high / BB upper)
    if abs(target2_mult - 2.5) < 1e-9 and not np.isnan(high20):
        target2 = max(high20, bb_u) if not np.isnan(bb_u) else high20
    else:
        target2 = target2_atr

    # Short: prefer fade near resistance / MA20 in down/range.
    # Explicit short multiples follow the screener sliders; otherwise keep
    # the prior structural target when a 20-day low and lower band exist.
    s_stop = stop_mult if short_stop_mult is None else short_stop_mult
    s_t1 = target1_mult if short_target1_mult is None else short_target1_mult
    s_t2 = target2_mult if short_target2_mult is None else short_target2_mult
    short_entry = max(price, ma20) if state in ("Down", "Range") else price
    short_stop = short_entry + s_stop * atr_v
    short_t1 = short_entry - s_t1 * atr_v
    if short_target2_mult is None and not np.isnan(low20) and not np.isnan(bb_l):
        short_t2 = min(low20, bb_l)
    else:
        short_t2 = short_entry - s_t2 * atr_v

    zone_a = ma20  # still above MA60
    zone_b = min(ma60, bb_l) if not np.isnan(bb_l) else ma60
    month_drop = float(row["ret_20"]) if not pd.isna(row.get("ret_20", np.nan)) else 0.0
    zone_c = "active" if (month_drop < -0.08 or rsi_v < 30) else "inactive"

    signals: list[str] = []
    swing_ok = state in ("StrongUp", "Up")
    swing_short_ok = state in ("Down", "Range")
    # Pullback buy condition (informative for today)
    if swing_ok and price <= ma20 * 1.01 and 40 <= rsi_v <= 55:
        if float(row["MACD_hist"]) > float(df["MACD_hist"].iloc[-2]) if len(df) > 1 else True:
            signals.append("pullback_buy_watch")
    if (
        swing_ok
        and price >= high20
        and vol_ratio is not None
        and vol_ratio >= 1.2
    ):
        signals.append("breakout_buy_watch")
    if swing_short_ok and price >= ma20 * 0.99 and rsi_v >= 65:
        signals.append("short_fade_watch")
    if price < ma60:
        signals.append("below_ma60")
    if rsi_v >= 70:
        signals.append("rsi_overbought")
    if rsi_v <= 30:
        signals.append("rsi_oversold")

    def _opt(value: float) -> Optional[float]:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        return round(float(value), 4)

    k9 = float(row["K9"]) if "K9" in row and not pd.isna(row["K9"]) else float("nan")
    d9 = float(row["D9"]) if "D9" in row and not pd.isna(row["D9"]) else float("nan")
    hist_prev = float("nan")
    if len(df) > 1 and "MACD_hist" in df.columns and not pd.isna(df["MACD_hist"].iloc[-2]):
        hist_prev = float(df["MACD_hist"].iloc[-2])

    if state == "StrongUp":
        size_hint = "full_swing"
    elif state == "Up":
        size_hint = "half_swing"
    elif state == "Range":
        size_hint = "range_only"
    else:
        size_hint = "no_swing_long"

    return TradeLevels(
        as_of=str(df.index[-1].date()),
        price=round(price, 4),
        trend_state=state,
        ma5=round(ma5, 4),
        ma10=round(ma10, 4),
        ma20=round(ma20, 4),
        ma30=round(ma30, 4) if not np.isnan(ma30) else None,
        ma60=round(ma60, 4),
        ma90=round(ma90, 4) if not np.isnan(ma90) else None,
        ma120=round(ma120, 4) if not np.isnan(ma120) else None,
        rsi14=round(rsi_v, 2),
        macd=round(float(row["MACD"]), 4),
        macd_signal=round(float(row["MACD_signal"]), 4),
        macd_hist=round(float(row["MACD_hist"]), 4),
        atr14=round(atr_v, 4),
        bb_lower=round(bb_l, 4),
        bb_mid=round(bb_m, 4),
        bb_upper=round(bb_u, 4),
        vol_ratio=None if vol_ratio is None else round(vol_ratio, 3),
        support_near=round(support_near, 4),
        support_mid=round(support_mid, 4),
        resistance_near=round(resistance_near, 4),
        stop_ref=round(stop_ref, 4),
        swing_buy_pullback=round(ma20, 4),
        swing_buy_breakout=round(high20, 4),
        target1=round(target1, 4),
        target2=round(float(target2), 4),
        zone_a=round(zone_a, 4),
        zone_b=round(zone_b, 4),
        zone_c_trigger=zone_c,
        swing_long_allowed=swing_ok,
        position_size_hint=size_hint,
        signals=signals,
        short_entry_ref=round(short_entry, 4),
        short_stop_ref=round(short_stop, 4),
        short_target1=round(short_t1, 4),
        short_target2=round(float(short_t2), 4),
        swing_short_allowed=swing_short_ok,
        k9=_opt(k9),
        d9=_opt(d9),
        high_20=_opt(high20),
        low_20=_opt(low20),
        macd_hist_prev=_opt(hist_prev),
    )
