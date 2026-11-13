"""Simple swing backtest: pullback buy under StrongUp/Up filter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .signals import attach_trend_state


@dataclass
class BacktestResult:
    start: str
    end: str
    bars: int
    trades: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    strategy_total_return_pct: float
    strategy_annualized_pct: float
    strategy_max_drawdown_pct: float
    buyhold_total_return_pct: float
    buyhold_annualized_pct: float
    buyhold_max_drawdown_pct: float
    equity_curve: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min() * 100.0)


def _annualize(total_return: float, n_days: int) -> float:
    if n_days <= 0:
        return 0.0
    years = n_days / 252.0
    if years <= 0:
        return 0.0
    return float(((1 + total_return) ** (1 / years) - 1) * 100.0)


def run_swing_backtest(df: pd.DataFrame) -> BacktestResult:
    """
    Rules (long only):
    - Enter when trend_state in {StrongUp, Up}, Close touches/crosses below MA20,
      RSI between 40-55, and MACD hist not strongly deteriorating.
    - Exit: Close < MA20 (trailing) OR Close <= entry - 1.5*ATR OR Close < MA60
      OR take-profit at entry + 2.5*ATR (simplified single exit vs multi-target).
    - One position at a time; all-in unit size.
    """
    data = attach_trend_state(df)
    data = data.dropna(subset=["MA20", "MA60", "ATR14", "RSI14", "MACD_hist"])

    cash = 1.0
    position = 0.0
    entry = 0.0
    equity = []
    trade_returns: list[float] = []

    for i in range(1, len(data)):
        row = data.iloc[i]
        prev = data.iloc[i - 1]
        date = data.index[i]
        price = float(row["Close"])
        state = row["trend_state"]
        ma20 = float(row["MA20"])
        ma60 = float(row["MA60"])
        atr_v = float(row["ATR14"])
        rsi_v = float(row["RSI14"])

        # Mark to market
        if position > 0:
            eq = position * price
        else:
            eq = cash
        equity.append({"date": str(date.date()), "equity": eq})

        if position == 0:
            pullback = price <= ma20 * 1.005 and float(prev["Close"]) >= float(prev["MA20"]) * 0.995
            rsi_ok = 40 <= rsi_v <= 55
            macd_ok = float(row["MACD_hist"]) >= float(prev["MACD_hist"]) - atr_v * 0.01
            if state in ("StrongUp", "Up") and pullback and rsi_ok and macd_ok:
                position = cash / price
                entry = price
                cash = 0.0
        else:
            stop = entry - 1.5 * atr_v
            tp = entry + 2.5 * atr_v
            exit_reason = None
            if price <= stop:
                exit_reason = "stop"
            elif price < ma60:
                exit_reason = "ma60"
            elif price < ma20:
                exit_reason = "ma20_trail"
            elif price >= tp:
                exit_reason = "tp"

            if exit_reason:
                cash = position * price
                ret = price / entry - 1.0
                trade_returns.append(ret)
                position = 0.0
                entry = 0.0

    # Close open position at end
    if position > 0:
        last = float(data["Close"].iloc[-1])
        cash = position * last
        trade_returns.append(last / entry - 1.0)
        position = 0.0
        equity[-1]["equity"] = cash

    eq_s = pd.Series([e["equity"] for e in equity], index=[e["date"] for e in equity])
    if eq_s.empty:
        eq_s = pd.Series([1.0])

    strat_total = float(eq_s.iloc[-1] / eq_s.iloc[0] - 1.0) if len(eq_s) else 0.0
    bh = data["Close"] / data["Close"].iloc[0]
    bh_total = float(bh.iloc[-1] - 1.0)
    n_days = len(data)

    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]
    win_rate = (len(wins) / len(trade_returns) * 100.0) if trade_returns else 0.0
    avg_win = float(np.mean(wins) * 100) if wins else 0.0
    avg_loss = float(np.mean(losses) * 100) if losses else 0.0
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = float(gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Downsample equity curve for canvas (~80 points)
    step = max(1, len(equity) // 80)
    curve = equity[::step]
    if equity and curve[-1] != equity[-1]:
        curve.append(equity[-1])

    return BacktestResult(
        start=str(data.index[0].date()),
        end=str(data.index[-1].date()),
        bars=n_days,
        trades=len(trade_returns),
        win_rate_pct=round(win_rate, 2),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(pf, 3) if pf != float("inf") else 999.0,
        strategy_total_return_pct=round(strat_total * 100, 2),
        strategy_annualized_pct=round(_annualize(strat_total, n_days), 2),
        strategy_max_drawdown_pct=round(_max_drawdown(eq_s), 2),
        buyhold_total_return_pct=round(bh_total * 100, 2),
        buyhold_annualized_pct=round(_annualize(bh_total, n_days), 2),
        buyhold_max_drawdown_pct=round(_max_drawdown(bh), 2),
        equity_curve=curve,
    )
