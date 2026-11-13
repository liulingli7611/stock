# 0050 / 00919 波段＋中長期策略分析系統

Version: 1.0.2.

針對元大台灣50（0050）與群益台灣精選高息（00919）的分析工具：基本面濾網、技術面趨勢判定、價格區間／買賣點、簡易回測，並產出 Markdown 報告、HTML deck 與 Canvas 儀表板。

靜態選股器快照會部署到 GitHub Pages（`docs/`）。本機即時版：`./serve` → http://127.0.0.1:5050/

**免責聲明**：本系統僅供研究與決策參考，不構成投資建議。實盤交易請自行評估風險。

## 開盤前自動更新個股價位

每個交易日（週一至週五）**08:30** 會重跑選股，用畫面上啟用的技術濾網（同一邊過半數成立）加上趨勢與基本面，列出做多和做空，並更新參考價、目標價、停損價（用前一交易日收盤）。紀錄在 `logs/preopen.log`。電腦需開機且醒著；若 8:30 在睡眠，醒來後會補跑。

手動立刻更新個股資料：說「更新」，或執行 `./preopen`。

## 更新（唯一需要記住的指令）

```bash
./update
```

會自動建立／使用 `.venv`、抓最新行情、重跑 0050＋00919 策略分析、同步 Canvas、產出 deck。

## 產出一覽

| 標的 | 報告 | JSON／訊號 | Canvas | Deck |
|------|------|------------|--------|------|
| 0050 | `reports/0050_latest.md` | `output/0050_*` | `0050_strategy.canvas.tsx` | `reports/0050_strategy_deck.html` |
| 00919 | `reports/00919_latest.md` | `output/00919_*` | `00919_strategy.canvas.tsx` | `reports/00919_strategy_deck.html` |

00919 另有關注評估：`python -m src.eval_00919` → `reports/00919_watch_eval.md`。

## 單獨執行

```bash
source .venv/bin/activate
python -m src.run_analysis          # 0050
python -m src.run_00919_analysis    # 00919 策略
python -m src.eval_00919            # 00919 關注評估（可選）
```

## 策略摘要（兩檔共用框架）

- **波段**：日線為主、週線濾網；狀態 `StrongUp` / `Up` / `Range` / `Down`
- **中長期**：每月資金 50% 定投；另 50% 僅在加碼區分批投入
- **風險預設**：可接受最大回撤約 15%；停損約 1.5×ATR
- **00919 差異**：濾網看金融權重／殖利率品質，不以台積電為核心曝險
