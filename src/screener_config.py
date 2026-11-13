"""Configurable parameters for the constituent screener."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from typing import Any, Optional

from src.fetch_holdings import CONSTITUENT_ETFS
from src.tech_filters import load_enabled, parse_filter_list

UNIVERSE_CHOICES = [*CONSTITUENT_ETFS, "both", "all", "custom"]


@dataclass
class ScreenerConfig:
    universe: str = "both"  # constituent ETF code | both | all | custom
    min_yield: float = 0.03
    max_pe: float = 25.0
    min_pe_short: float = 35.0
    pe_vs_median_max: float = 0.9  # PE <= median * this → undervalued bonus
    pe_vs_median_min_short: float = 1.2  # PE >= median * this → overvalued bonus
    min_weight: float = 0.0
    atr_stop: float = 1.5
    atr_target1: float = 2.5
    atr_target2: float = 4.0
    atr_stop_short: float = 1.2
    atr_target1_short: float = 2.0
    atr_target2_short: float = 3.0
    rsi_long_max: float = 60.0
    rsi_short_min: float = 60.0
    tech_filters: tuple[str, ...] = ("rsi",)
    long_trends: tuple[str, ...] = ("StrongUp", "Up")
    short_trends: tuple[str, ...] = ("Down", "Range")
    top_n: int = 20
    period: str = "2y"
    use_cache_holdings: bool = False
    use_cache_prices: bool = False
    sleep_sec: float = 0.15  # throttle between yfinance calls

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["long_trends"] = list(self.long_trends)
        d["short_trends"] = list(self.short_trends)
        d["tech_filters"] = list(self.tech_filters)
        return d


def _parse_trends(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("trend list cannot be empty")
    return tuple(parts)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Screen constituent ETFs for long/short reference levels "
        "(research only — not investment advice)."
    )
    p.add_argument("--universe", choices=list(UNIVERSE_CHOICES), default="both")
    p.add_argument("--min-yield", type=float, default=0.03, help="Min dividend yield for long filter")
    p.add_argument("--max-pe", type=float, default=25.0, help="Max trailing PE for long filter")
    p.add_argument(
        "--min-pe-short",
        type=float,
        default=35.0,
        help="Min trailing PE for short filter",
    )
    p.add_argument(
        "--pe-vs-median-max",
        type=float,
        default=0.9,
        help="Long bonus if PE <= universe median * this",
    )
    p.add_argument(
        "--pe-vs-median-min-short",
        type=float,
        default=1.2,
        help="Short bonus if PE >= universe median * this",
    )
    p.add_argument("--min-weight", type=float, default=0.0, help="Min ETF weight %% to include")
    p.add_argument("--atr-stop", type=float, default=1.5)
    p.add_argument("--atr-target1", type=float, default=2.5)
    p.add_argument("--atr-target2", type=float, default=4.0)
    p.add_argument("--atr-stop-short", type=float, default=1.2)
    p.add_argument("--atr-target1-short", type=float, default=2.0)
    p.add_argument("--atr-target2-short", type=float, default=3.0)
    p.add_argument("--rsi-long-max", type=float, default=60.0)
    p.add_argument("--rsi-short-min", type=float, default=60.0)
    p.add_argument(
        "--tech-filters",
        default="",
        help="Comma-separated technical filters. Empty uses data/tech_filters.json "
        "(the filters shown on the screener). "
        "Known: rsi,macd_cross,macd_hist,kd,ma_align_s,ma_align_m,price_ma,bias_ma20,bb_mid,volume,breakout_20,atr_calm",
    )
    p.add_argument(
        "--long-trends",
        type=_parse_trends,
        default="StrongUp,Up",
        help="Comma-separated trend states allowed for long",
    )
    p.add_argument(
        "--short-trends",
        type=_parse_trends,
        default="Down,Range",
        help="Comma-separated trend states allowed for short",
    )
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--period", default="2y", help="yfinance history period for each stock")
    p.add_argument("--use-cache-holdings", action="store_true")
    p.add_argument("--use-cache-prices", action="store_true")
    p.add_argument("--sleep", type=float, default=0.15, dest="sleep_sec")
    return p


def config_from_args(args: Optional[argparse.Namespace] = None) -> ScreenerConfig:
    if args is None:
        args = build_arg_parser().parse_args()
    long_trends = args.long_trends
    short_trends = args.short_trends
    if isinstance(long_trends, str):
        long_trends = _parse_trends(long_trends)
    if isinstance(short_trends, str):
        short_trends = _parse_trends(short_trends)
    tech_filters = args.tech_filters
    if isinstance(tech_filters, str):
        try:
            if not tech_filters.strip():
                tech_filters = tuple(load_enabled())
            else:
                tech_filters = parse_filter_list(tech_filters)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
    return ScreenerConfig(
        universe=args.universe,
        min_yield=args.min_yield,
        max_pe=args.max_pe,
        min_pe_short=args.min_pe_short,
        pe_vs_median_max=args.pe_vs_median_max,
        pe_vs_median_min_short=args.pe_vs_median_min_short,
        min_weight=args.min_weight,
        atr_stop=args.atr_stop,
        atr_target1=args.atr_target1,
        atr_target2=args.atr_target2,
        atr_stop_short=args.atr_stop_short,
        atr_target1_short=args.atr_target1_short,
        atr_target2_short=args.atr_target2_short,
        rsi_long_max=args.rsi_long_max,
        rsi_short_min=args.rsi_short_min,
        tech_filters=tuple(tech_filters),
        long_trends=tuple(long_trends),
        short_trends=tuple(short_trends),
        top_n=args.top_n,
        period=args.period,
        use_cache_holdings=args.use_cache_holdings,
        use_cache_prices=args.use_cache_prices,
        sleep_sec=args.sleep_sec,
    )
