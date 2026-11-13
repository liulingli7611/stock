"""Build reports/00919_strategy_deck.html from output/00919_latest.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "output" / "00919_latest.json"
OUT_PATH = ROOT / "reports" / "00919_strategy_deck.html"


def _r(v, nd=2):
    if v is None:
        return "n/a"
    try:
        float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{float(v):.{nd}f}"


def _badge(bias: str) -> str:
    b = (bias or "neutral").lower()
    if b in ("accumulate", "bullish", "strongup"):
        cls = "ok"
    elif b in ("defensive", "cautious", "down"):
        cls = "bad"
    elif b in ("warn", "warning", "range"):
        cls = "warn"
    else:
        cls = "neutral"
    return f'<span class="badge {cls}">{bias}</span>'


def build_html(data: dict) -> str:
    fund = data["fundamentals"]
    levels = data["levels"]
    bt = data["backtest"]
    as_of = levels["as_of"]
    price = _r(levels["price"])
    trend = levels["trend_state"]

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>00919 波段＋中長期策略分析</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg-0: #071018; --bg-1: #0c1a24; --ink: #e8f1f4; --muted: #8aa0ab;
      --line: rgba(232, 241, 244, 0.12); --panel: rgba(14, 32, 44, 0.72);
      --teal: #3ecfb2; --amber: #f0b35a; --rose: #f07178; --sky: #7eb8ff;
      --radius: 18px; --ease: cubic-bezier(0.22, 1, 0.36, 1);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ height: 100%; background: var(--bg-0); color: var(--ink);
      font-family: "Noto Sans TC", "Bricolage Grotesque", sans-serif; overflow: hidden; }}
    body::before {{
      content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
      background:
        radial-gradient(ellipse 80% 55% at 12% -10%, rgba(62, 207, 178, 0.22), transparent 55%),
        radial-gradient(ellipse 70% 50% at 92% 8%, rgba(240, 179, 90, 0.16), transparent 50%),
        linear-gradient(165deg, var(--bg-0), var(--bg-1) 45%, #08141c);
    }}
    .deck {{ position: relative; z-index: 1; height: 100%; width: 100%; }}
    .slide {{
      position: absolute; inset: 0; display: none; flex-direction: column;
      padding: 2.2rem 2.6rem 4.5rem; overflow: auto;
    }}
    .slide.active {{ display: flex; animation: in 0.45s var(--ease); }}
    @keyframes in {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
    .kicker {{ color: var(--teal); font-size: 0.78rem; letter-spacing: 0.14em; text-transform: uppercase; margin-bottom: 0.4rem; }}
    h1 {{ font-family: "Bricolage Grotesque", sans-serif; font-size: clamp(1.8rem, 4vw, 2.6rem); line-height: 1.15; }}
    h2 {{ font-family: "Bricolage Grotesque", sans-serif; font-size: 1.55rem; margin-bottom: 0.85rem; }}
    h3 {{ font-size: 0.95rem; margin-bottom: 0.55rem; color: var(--sky); }}
    .lead {{ color: var(--muted); max-width: 42rem; line-height: 1.55; margin-top: 0.6rem; }}
    .grid {{ display: grid; gap: 0.85rem; }}
    .grid-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .grid-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .grid-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .panel {{
      background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
      padding: 1rem 1.1rem; backdrop-filter: blur(10px);
    }}
    .stat-label {{ color: var(--muted); font-size: 0.72rem; letter-spacing: 0.06em; }}
    .stat-value {{ font-family: "Bricolage Grotesque", sans-serif; font-size: 1.55rem; margin-top: 0.25rem; }}
    .stat-sub {{ color: var(--muted); font-size: 0.8rem; margin-top: 0.35rem; }}
    .badge {{ display: inline-block; padding: 0.15rem 0.45rem; border-radius: 999px; font-size: 0.72rem; border: 1px solid var(--line); }}
    .badge.ok {{ color: var(--teal); background: rgba(62,207,178,0.14); }}
    .badge.warn {{ color: var(--amber); background: rgba(240,179,90,0.14); }}
    .badge.bad {{ color: var(--rose); background: rgba(240,113,120,0.14); }}
    .badge.neutral {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ text-align: left; padding: 0.45rem 0.35rem; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 500; font-size: 0.75rem; }}
    ul.list {{ list-style: none; display: grid; gap: 0.55rem; }}
    ul.list li {{ display: flex; gap: 0.7rem; align-items: flex-start; color: var(--muted); font-size: 0.9rem; line-height: 1.45; }}
    ul.list .num {{
      flex: 0 0 2rem; height: 2rem; border-radius: 10px; display: grid; place-items: center;
      background: rgba(62,207,178,0.16); color: var(--teal); font-weight: 700; font-size: 0.8rem;
    }}
    .nav {{
      position: fixed; bottom: 1rem; left: 50%; transform: translateX(-50%); z-index: 5;
      display: flex; gap: 0.5rem; align-items: center; padding: 0.45rem 0.65rem;
      background: rgba(8, 18, 26, 0.88); border: 1px solid var(--line); border-radius: 999px;
    }}
    .nav button {{
      background: transparent; border: 1px solid var(--line); color: var(--ink);
      border-radius: 999px; padding: 0.35rem 0.75rem; cursor: pointer; font: inherit;
    }}
    .nav button:hover {{ border-color: var(--teal); color: var(--teal); }}
    .nav .idx {{ color: var(--muted); font-size: 0.8rem; min-width: 3.5rem; text-align: center; }}
    .chip {{ display: inline-block; padding: 0.25rem 0.6rem; border-radius: 999px;
      border: 1px solid var(--line); color: var(--muted); font-size: 0.78rem; margin-right: 0.35rem; }}
    @media (max-width: 900px) {{
      .grid-2, .grid-3, .grid-4 {{ grid-template-columns: 1fr; }}
      .slide {{ padding: 1.4rem 1.2rem 5rem; }}
    }}
  </style>
</head>
<body>
  <div class="deck" id="deck">
    <section class="slide active" data-title="封面">
      <p class="kicker">Capital · High Dividend Strategy</p>
      <h1>00919 波段＋中長期策略</h1>
      <p class="lead">群益台灣精選高息 — 與 0050 相同框架：基本面濾網、趨勢狀態、價格區間、波段回測。現金流部位為主，金融集中風險需同步控管。</p>
      <div class="grid grid-4" style="margin-top:1.4rem">
        <div class="panel"><div class="stat-label">資料日期</div><div class="stat-value" style="font-size:1.25rem">{as_of}</div></div>
        <div class="panel"><div class="stat-label">現價</div><div class="stat-value">{price}</div></div>
        <div class="panel"><div class="stat-label">趨勢</div><div class="stat-value" style="font-size:1.25rem">{trend}</div><div class="stat-sub">{_badge(trend)}</div></div>
        <div class="panel"><div class="stat-label">基本面</div><div class="stat-value" style="font-size:1.25rem">{fund['overall_bias']}</div><div class="stat-sub">上限 {_r(fund['position_cap_pct'], 0)}%</div></div>
      </div>
      <p style="margin-top:1.2rem"><span class="chip">研究參考 · 非投資建議</span><span class="chip">更新 ./update</span></p>
    </section>

    <section class="slide" data-title="基本面">
      <p class="kicker">Fundamentals</p>
      <h2>基本面環境濾網</h2>
      <div class="grid grid-4">
        <div class="panel"><div class="stat-label">年化波動</div><div class="stat-value">{_r(fund.get('annualized_volatility_pct'))}%</div><div class="stat-sub">{_badge(fund['vol_bias'])}</div></div>
        <div class="panel"><div class="stat-label">金融股權重</div><div class="stat-value">{_r(fund.get('financial_weight_pct'))}%</div><div class="stat-sub">{_badge(fund.get('financial_bias','neutral'))}</div></div>
        <div class="panel"><div class="stat-label">粗估殖利率</div><div class="stat-value">{_r(fund.get('cash_dividend_yield_pct'))}%</div><div class="stat-sub">勿外推為保證報酬</div></div>
        <div class="panel"><div class="stat-label">折溢價</div><div class="stat-value">{_r(fund.get('premium_pct'), 3)}%</div><div class="stat-sub">{_badge(fund['premium_bias'])}</div></div>
      </div>
      <div class="grid grid-2" style="margin-top:1rem">
        <div class="panel">
          <h3>中長期加碼</h3>
          <ul class="list">
            <li><span class="num">50%</span><div><strong style="color:var(--ink)">無條件定投</strong> — 現金流核心部位</div></li>
            <li><span class="num">50%</span><div><strong style="color:var(--ink)">逢低分批</strong> — 僅 Zone A/B/C；defensive 時暫停</div></li>
          </ul>
        </div>
        <div class="panel">
          <h3>結構提醒</h3>
          <p class="stat-sub" style="line-height:1.55">{fund.get('notes','')}</p>
        </div>
      </div>
    </section>

    <section class="slide" data-title="技術與區間">
      <p class="kicker">Levels</p>
      <h2>技術狀態與買賣參考</h2>
      <div class="grid grid-4" style="margin-bottom:1rem">
        <div class="panel"><div class="stat-label">RSI(14)</div><div class="stat-value">{_r(levels['rsi14'])}</div></div>
        <div class="panel"><div class="stat-label">MA20</div><div class="stat-value">{_r(levels['ma20'])}</div></div>
        <div class="panel"><div class="stat-label">支撐 / 壓力</div><div class="stat-value" style="font-size:1.15rem">{_r(levels['support_near'])} / {_r(levels['resistance_near'])}</div></div>
        <div class="panel"><div class="stat-label">部位提示</div><div class="stat-value" style="font-size:1.1rem">{levels['position_size_hint']}</div></div>
      </div>
      <div class="panel">
        <table>
          <thead><tr><th>類型</th><th>價位</th><th>說明</th></tr></thead>
          <tbody>
            <tr><td>回檔買</td><td>{_r(levels['swing_buy_pullback'])}</td><td>MA20 · 需 StrongUp/Up</td></tr>
            <tr><td>突破買</td><td>{_r(levels['swing_buy_breakout'])}</td><td>20日高＋量能</td></tr>
            <tr><td>目標1 / 2</td><td>{_r(levels['target1'])} / {_r(levels['target2'])}</td><td>+1.5ATR → 壓力區</td></tr>
            <tr><td>硬停損</td><td>{_r(levels['stop_ref'])}</td><td>−1.5ATR 或跌破 MA60</td></tr>
            <tr><td>Zone A / B</td><td>{_r(levels['zone_a'])} / {_r(levels['zone_b'])}</td><td>中長期加碼</td></tr>
            <tr><td>Zone C</td><td>{levels['zone_c_trigger']}</td><td>單月跌&gt;8% 或 RSI&lt;30</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="slide" data-title="回測">
      <p class="kicker">Backtest</p>
      <h2>波段回檔買 · 簡易回測</h2>
      <p class="lead" style="margin-bottom:1rem">{bt['start']} → {bt['end']} · {bt['bars']} 交易日 · 與 0050 相同規則</p>
      <div class="grid grid-4">
        <div class="panel"><div class="stat-label">策略總報酬</div><div class="stat-value">{_r(bt['strategy_total_return_pct'])}%</div><div class="stat-sub">年化 {_r(bt['strategy_annualized_pct'])}%</div></div>
        <div class="panel"><div class="stat-label">策略 MDD</div><div class="stat-value">{_r(bt['strategy_max_drawdown_pct'])}%</div></div>
        <div class="panel"><div class="stat-label">買進持有</div><div class="stat-value">{_r(bt['buyhold_total_return_pct'])}%</div><div class="stat-sub">年化 {_r(bt['buyhold_annualized_pct'])}%</div></div>
        <div class="panel"><div class="stat-label">勝率 / PF</div><div class="stat-value" style="font-size:1.25rem">{_r(bt['win_rate_pct'])}% / {_r(bt['profit_factor'])}</div><div class="stat-sub">{bt['trades']} 筆交易</div></div>
      </div>
      <div class="panel" style="margin-top:1rem">
        <h3>實務解讀</h3>
        <p class="stat-sub" style="line-height:1.55">中長期定投（現金流）為核心；波段僅在 StrongUp 回檔至 MA20、且 RSI 未過熱時小倉。金融權重高時，利率與金控景氣優於短線喊單。</p>
      </div>
    </section>

    <section class="slide" data-title="風險與更新">
      <p class="kicker">Risk & Update</p>
      <h2>風險與更新方式</h2>
      <div class="grid grid-2">
        <div class="panel">
          <h3>風險</h3>
          <ul class="list">
            <li><span class="num">1</span><div>金融集中約五成 — 利率／壽險評價敏感</div></li>
            <li><span class="num">2</span><div>配息可能含資本利得 — 淨值同步下滑</div></li>
            <li><span class="num">3</span><div>換股後風格漂移 — 名稱≠內涵</div></li>
          </ul>
        </div>
        <div class="panel">
          <h3>一鍵更新</h3>
          <p class="stat-sub" style="line-height:1.7; margin-top:0.4rem">
            <code style="color:var(--teal)">./update</code><br />
            或 <code style="color:var(--teal)">python -m src.run_00919_analysis</code><br /><br />
            報告：reports/00919_latest.md<br />
            Canvas：00919_strategy.canvas.tsx
          </p>
        </div>
      </div>
    </section>
  </div>

  <div class="nav">
    <button type="button" id="prev">上一頁</button>
    <span class="idx" id="idx">1 / 1</span>
    <button type="button" id="next">下一頁</button>
  </div>
  <script>
    const slides = [...document.querySelectorAll('.slide')];
    let i = 0;
    const idx = document.getElementById('idx');
    function show(n) {{
      i = (n + slides.length) % slides.length;
      slides.forEach((s, k) => s.classList.toggle('active', k === i));
      idx.textContent = (i + 1) + ' / ' + slides.length;
    }}
    document.getElementById('prev').onclick = () => show(i - 1);
    document.getElementById('next').onclick = () => show(i + 1);
    document.addEventListener('keydown', (e) => {{
      if (e.key === 'ArrowRight' || e.key === ' ') {{ e.preventDefault(); show(i + 1); }}
      if (e.key === 'ArrowLeft') show(i - 1);
    }});
    show(0);
  </script>
</body>
</html>
"""


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    # Strategy payload must have fundamentals/levels/backtest
    if "levels" not in data or "backtest" not in data:
        raise SystemExit("00919_latest.json is not strategy shape; run run_00919_analysis first")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build_html(data), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
