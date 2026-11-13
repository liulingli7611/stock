"""Fetch 0050 daily OHLCV (adjusted) and optional NAV premium data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_TICKER = "0050.TW"
TSMC_TICKER = "2330.TW"


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance columns to Open/High/Low/Close/Volume/AdjClose."""
    if df.empty:
        raise ValueError("Empty price dataframe returned from data source")

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    rename = {
        "Adj Close": "AdjClose",
        "adj close": "AdjClose",
        "Open": "Open",
        "High": "High",
        "Low": "Low",
        "Close": "Close",
        "Volume": "Volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    if "AdjClose" not in df.columns:
        df["AdjClose"] = df["Close"]

    out = df[required + ["AdjClose"]].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    # Prefer adjusted close for analysis; scale OHLC by adj factor when possible
    factor = (out["AdjClose"] / out["Close"]).replace([pd.NA, float("inf")], 1.0).fillna(1.0)
    for col in ("Open", "High", "Low", "Close"):
        out[col] = out[col] * factor
    out = out.drop(columns=["AdjClose"])
    out = out.dropna(subset=["Close"])
    out["Volume"] = out["Volume"].fillna(0).astype("int64")
    return out


def fetch_daily(
    ticker: str = DEFAULT_TICKER,
    period: str = "5y",
    cache_path: Optional[Path] = None,
    use_cache: bool = False,
) -> pd.DataFrame:
    """Download daily bars. Uses adjusted prices for splits/dividends."""
    cache_path = cache_path or (DATA_DIR / "0050_daily.csv")
    if use_cache and cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["Date"], index_col="Date")
        return df

    try:
        raw = yf.download(
            ticker,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        df = _normalize_ohlcv(raw)
    except Exception as exc:
        if cache_path.exists():
            print(f"Fetch failed ({exc}); using cache {cache_path}")
            return pd.read_csv(cache_path, parse_dates=["Date"], index_col="Date")
        raise

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index_label="Date")
    return df


def fetch_tsmc_daily(period: str = "5y") -> pd.DataFrame:
    """Fetch TSMC for concentration / trend cross-check."""
    raw = yf.download(
        TSMC_TICKER,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    return _normalize_ohlcv(raw)


def fetch_nav_premium_estimate(
    market_price: float,
    timeout: float = 8.0,
) -> dict:
    """
    Best-effort NAV / premium snapshot.

    Tries MoneyDJ-style public pages; falls back to unknown if unavailable.
    """
    result = {
        "nav": None,
        "market_price": market_price,
        "premium_pct": None,
        "source": None,
        "as_of": None,
        "note": "NAV unavailable; leave blank for manual update",
    }
    # yfinance sometimes exposes navPrice for ETFs
    try:
        info = yf.Ticker(DEFAULT_TICKER).info or {}
        nav = info.get("navPrice") or info.get("netAssets")
        # navPrice is more useful; netAssets is AUM
        if info.get("navPrice"):
            nav_v = float(info["navPrice"])
            prem = (market_price / nav_v - 1.0) * 100.0
            # 0050 usually trades within ~±0.5%; larger gaps often mean stale NAV
            if abs(prem) > 1.0:
                result.update(
                    {
                        "nav": round(nav_v, 4),
                        "premium_pct": None,
                        "source": "yfinance.info.navPrice",
                        "note": f"Ignored stale/outlier premium {prem:.2f}% (NAV may be outdated)",
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
            return result
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"yfinance NAV failed: {exc}"

    # Optional lightweight HTTP probe (may fail without network / blocked)
    try:
        url = "https://www.moneydj.com/etf/x/basic/basic0003.xdjhtm?etfid=0050.tw"
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok and "淨值" in resp.text:
            result["source"] = "moneydj"
            result["note"] = "Page reachable; parse manually if needed (HTML structure varies)"
    except Exception:
        pass
    return result


def save_meta(meta: dict, path: Optional[Path] = None) -> Path:
    path = path or (DATA_DIR / "0050_meta.json")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    bars = fetch_daily()
    print(bars.tail())
    print("rows:", len(bars))
