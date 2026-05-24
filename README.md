# Group 13 — OR 期末專案：便利商店個人化餐食推薦

## 目錄結構
```
期末/
├── Final_Project_Proposal_Group13.pdf   # 第一階段提案（已交）
├── OR114-2_finalProject.pdf              # 課程規範
├── data/                                  # 資料來源（即時爬取）
│   ├── familymart_products_priced.csv     # 581 項真實商品 + 真實零售價（推薦使用）
│   ├── familymart_products_real.csv       # 581 項即時爬取的真實營養標示
│   ├── familymart_tier_prices.csv         # 265 項鮮食促銷頁價格分級
│   ├── mart_prices_raw.csv                # 1,653 項全家行動購電商價
│   ├── familymart_products.csv            # 75 項 curated fallback
│   └── familymart_combos.csv              # 30 組 curated 優惠
├── src/                                   # 程式碼
│   ├── preprocessing.py                   # Mifflin-St Jeor → 單餐限制
│   ├── data_loader.py                     # 真實 / 隨機例題載入
│   ├── model_milp.py                      # Gurobi MILP 模型
│   ├── heuristic_proposed.py              # 本研究 GRASP-LS 啟發式
│   ├── heuristic_baseline.py              # 簡單貪婪 baseline
│   ├── run_experiments.py                 # 全部實驗
│   ├── build_tables.py                    # LaTeX 表格生成
│   ├── visualize.py                       # 圖表生成
│   ├── scrape_familymart.py               # 食在購安心 API scraper（營養）
│   ├── scrape_freshfood_prices.py         # 鮮食促銷頁價格 scraper + merger
│   ├── scrape_prices.py                   # 全家行動購 GraphQL scraper
│   ├── probe_mart.py                      # SPA XHR 逆向工程
│   ├── screenshot_webapp.py               # Playwright 截圖
│   └── sanity_check.py                    # 求解器 smoke test
├── webapp/                                # Flask 互動式 web 應用
│   ├── app.py
│   ├── templates/index.html
│   └── static/{style.css, app.js}
├── results/                               # 實驗輸出
│   ├── real_world.csv                     # 18 個真實例題結果
│   ├── random.csv                         # 30 個隨機例題結果
│   ├── sensitivity.csv                    # β / γ 敏感度
│   ├── figs/                              # 8 張圖（含 webapp 截圖）
│   └── tables/                            # LaTeX 表格
├── report/
│   ├── report.tex                         # 12 頁限制以內 final report
│   ├── report.pdf
│   └── abstract.md                        # 200-word 摘要
└── slides/
    ├── slides.tex                         # 投影片
    └── slides.pdf
```

## 重現實驗
```bash
# 安裝依賴
pip install gurobipy pandas numpy matplotlib

# 跑全部實驗（生 CSV）
python -X utf8 src/run_experiments.py

# 建表
python -X utf8 src/build_tables.py

# 畫圖
python -X utf8 src/visualize.py

# 編譯報告 / 投影片
cd report && xelatex report.tex && xelatex report.tex
cd ../slides && xelatex slides.tex && xelatex slides.tex
```

## 模型核心
- **變數：** $a_i \in \{0,1\}$ (單品), $y_k \in \{0,1\}$ (優惠組合), $x_i = a_i + \sum_{k: i \in S_k} y_k$
- **目標：** 最小化 $\alpha \cdot \text{總成本} - \beta \cdot \text{總蛋白} + \gamma \cdot \text{歷史懲罰} + \sum \lambda \cdot \text{鬆弛}$
- **硬限制：** 互斥、預算、熱量區間、商品數量、正餐主食+蛋白質
- **軟限制：** 蛋白質下限、脂肪/碳水區間、糖/鈉上限

## 啟發式 GRASP-LS
1. **Greedy Randomized Construction**：依綜合分數 $\sigma$ 建 RCL，隨機抽取
2. **Local Search**：1-1 swap / 1-0 drop / 0-1 add / combo-swap，首改善
3. **Multi-start**：$K_\text{restart}=25$ 種子，回傳最佳

## 主要結果
- MILP：48 個例題全找全域最佳
- GRASP-LS：100% feasible，平均 gap 9.2% (真實) / 3% (隨機)
- Greedy baseline：56% feasible，gap 動輒 100--400%

## 成員
- B13705005 宋宇倫
- B13705011 陳芃慈
- B13705020 陳鼎元
- B13705029 蔡冠毅
