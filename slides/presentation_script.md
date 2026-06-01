# Presentation Script — Optimization-Based Meal Recommendation for Convenience Stores
**Group 13 · Operations Research 2026 · Final Project**
Slides: `slides.pdf` (20 pages, one slide per page — no build/overlay steps). Target ≈ 14 min talk + ~2 min live demo.

## Speaker map (4 members)
| Speaker | Slides | Section |
|---|---|---|
| **P1 — 宋宇倫** | 1–3 | Title, Motivation, Problem definition |
| **P2 — 陳芃慈** | 4–7 | Preprocessing & MILP model |
| **P3 — 陳鼎元** | 8–11 | GRASP-LS algorithm & Data |
| **P4 — 蔡冠毅** | 12–20 | Results, **live web-app demo (slide 14)**, Conclusion |

---

## P1 — 宋宇倫  (Slides 1–3, ~2.5 min)

### Slide 1 — Title  (~30s)
> Good afternoon, everyone. We are Group 13, and our project is *Optimization-Based Meal Recommendation for Convenience Stores*. The idea is to combine an exact MILP model with a self-designed GRASP-LS heuristic, so we can recommend a single, balanced convenience-store meal that fits each user’s budget and nutrition needs. I’m 宋宇倫 — I’ll cover the motivation and the problem, and my teammates will take you through the model, the algorithm, the results, and a live demo.

### Slide 2 — Background & Motivation  (~50s)
> For students and office workers, convenience stores are the most frequent real-time meal channel — high density, fast, and every item is fully labeled. But a single pick juggles many goals at once: cost, calories, protein, sugar, sodium, and satiety. On top of that, bundle promotions — like “rice ball plus drink” — change the price you actually pay, so the cheapest combination isn’t obvious. The key message of this slide is that ranking by one metric isn’t enough; we genuinely need constrained optimization.

### Slide 3 — Decision Maker: Inputs, Outputs, Fallback  (~50s)
> So let’s define the problem. The decision maker is the user. The inputs are a scenario — light, regular, or late-night; a profile — sex, age, height, weight, activity; a goal — maintain, cut, or bulk; and a budget cap B. The output is a single-meal recommendation: individual items plus any promo bundles, with the expected nutrition and total cost. And importantly, if the constraints are too tight to satisfy exactly, we still return the closest feasible alternative by relaxing some soft constraints. With that, 陳芃慈 will present the model.

---

## P2 — 陳芃慈  (Slides 4–7, ~3.5 min)

### Slide 4 — Preprocessing  (~50s)
> Thanks. Before optimizing, we turn the profile into concrete numbers. The pipeline is: profile to BMR to TDEE to goal-adjusted calories to single-meal limits. We use the Mifflin–St Jeor formula for BMR, multiply by an activity factor for TDEE — the daily calorie need — and adjust by goal: zero for maintain, minus 500 for cutting, plus 300 for bulking. Then we scale down to one meal using a scenario ratio: a regular meal is about 30 to 45 percent of daily calories and up to 5 items, while light and late-night meals are smaller and capped at 3.

### Slide 5 — MILP Decision Variables & Structure  (~45s)
> Now the model. We have two sets of binary variables: a_i for whether a single item is selected, and y_k for whether a bundle is activated. We define an auxiliary count x_i — the total of item i across singles and bundles — capped at one so nothing is double-counted. And we add non-negative slack variables for protein, fat, carbs, sugar, and sodium, which let the model relax the soft targets when needed.

### Slide 6 — Tiered Memory (MLFQ-style)  (~45s)
> This slide is how we model diversity. Borrowing the multi-level feedback queue idea from operating systems: recent picks get higher penalties, and older items gradually fade. The tier weights are 5, 2.5, 1, and 0.3, and if an item is recommended again it jumps back to the top tier. We use two terms — h_i penalizes the exact same item, and g_i penalizes the same category, like all soy milks — so the model can’t just swap one soy milk for another and call it variety.

### Slide 7 — MILP Objective & Constraints  (~55s)
> Putting it together, we minimize alpha times total cost, minus beta times protein — so beta rewards protein — plus the history and category penalties, plus the weighted slacks. The hard constraints are non-negotiable: budget, the calorie range, mutual exclusion, the meal structure — at most one drink and one dessert, and a regular meal needs one main plus at least one protein source — a sodium hard cap at 1.5 times the limit, and the item-count cap. The soft constraints — protein floor, fat and carb ranges, sugar and sodium — are absorbed by the slacks. These weights simply set the relative importance of cost, protein, repetition, and soft-constraint violations, so users can dial in their own priorities. 陳鼎元 will now explain how we solve this.

---

## P3 — 陳鼎元  (Slides 8–11, ~3.5 min)

### Slide 8 — Why a Heuristic in Addition to Gurobi?  (~45s)
> Thanks. We do solve the MILP exactly with Gurobi, but the project also asks us to design our own algorithm and measure how close it gets. There are practical reasons too: a heuristic is license-free and edge-deployable, and extensible to multiple chains. It’s also “anytime” — it can stop early and still return the best meal found so far, which is exactly what an interactive app needs when it has to answer in about two seconds.

### Slide 9 — GRASP-LS: Algorithm Flowchart  (~55s)
> This flowchart walks through GRASP-LS, which has three stages. First, Greedy Randomized Construction — the GRC box: we score every candidate with a composite score, build a restricted candidate list of the top items, and sample randomly; this step is structure-aware, placing a main dish first and respecting the drink and dessert caps. Second, Local Search with first-improvement, using four moves: swap, drop, add, and bundle-swap. Third, the loop back you see on the right — multi-start: we repeat the construct-and-improve cycle 25 times from different random seeds, keeping a pool of the best solutions. For deployment, we sample from the epsilon-best set within 8 of optimal for variety, and fall back to the exact MILP if a tight budget leaves GRASP-LS infeasible.

### Slide 10 — Composite Score  (~45s)
> This is the “eye” of the heuristic — the score that ranks each product. It rewards protein and structural fit — mains and protein sources get a bonus. It penalizes cost, excess calories, sodium, sugar, and repetition from the tiered history. And bundles aren’t an afterthought — we treat them as “super-items,” prioritized by their discount, so good promotions get pulled in early.

### Slide 11 — Dataset  (~50s)
> A quick word on data, because it’s all real. We scraped FamilyMart’s official food-safety API for nutrition and the promo page for the real tiered prices. From 581 products we filtered out family-size packs to get 488. Of those, 124 fresh-food items use real tiered prices and the rest use market-calibrated prices, because the e-commerce site only lists whole-case prices. We built 18 real-world instances from 6 users across 3 scenarios, plus 30 random instances up to 300 items. On top of size, we also cross a two-by-two of budget and protein-target scenarios — tight versus loose budget, high versus loose protein — for stress testing. 蔡冠毅 will now show the results and a live demo.

---

## P4 — 蔡冠毅  (Slides 12–20, ~5 min incl. demo)

### Slide 12 — Real Scenario: MILP vs.\ GRASP-LS vs.\ Greedy  (~45s)
> Thanks. Here’s a concrete case — a male user, cutting, regular meal. Both MILP and GRASP-LS return a structurally complete, feasible meal — a main, a side, a drink, and a dessert — at NT$110, hitting every target. The naive greedy baseline fails: it skips a main dish and breaks the sodium cap, so it’s infeasible. This one example already shows why ranking alone isn’t enough.

### Slide 13 — 18 Real Instances  (~45s)
> Across all 18 real instances the pattern holds. MILP is the global optimum by definition. GRASP-LS is 100% hard-feasible with an average gap of just 7.1%, and 12 of the 18 are exactly optimal. Greedy is infeasible on every instance once we enforce structure and the sodium cap. And the non-zero gaps appear mainly in the regular-meal scenario, where the structural constraints make the feasible set very narrow.

### Slide 14 — Interactive Web App + **LIVE DEMO**  (~2 min)
> And all of this runs in a real Flask web app. Let me switch to a live demo.

**>>> DEMO STEPS — switch from slides to the browser at `http://127.0.0.1:5000` <<<**
1. **Show the page** — point out the title and the input form on the left.
2. **Fill the form:** Male · age 22 · height 175 · weight 70 · activity Medium (中) · goal Maintain (維持) · scenario Regular (正餐) · budget 120.
3. **Click “推薦這一餐” (Recommend)** — note it responds in ~2–3 seconds.
4. **Walk the result card:** the chosen items + bundle; **total cost (本餐花費)** on the far left; the “single-meal limits” bars all showing **達標 (on-target)**.
5. **Open “進階：模型權重設定”** (advanced weights). Drag the **β (protein) slider** up, click Recommend again → the meal shifts toward higher-protein items. *This is the “personalization handle.”*
6. **Click “近期紀錄” (Recent history)** — show the tiered **taste memory** modal (just-ate / recent / long-unseen), and that re-recommending avoids repeating recent items.
7. **Switch back to the slides.**

> *(closing on slide 14)* So the full pipeline — input, Mifflin–St Jeor conversion, GRASP-LS or MILP solving, and a real-time recommendation — runs interactively on all 488 real products.

### Slide 15 — Random Instances: Scalability & Gap  (~45s)
> On the random instances we test scalability. GRASP-LS stays scalable with a 4.9% average gap and is feasible on 28 of 30 instances. Greedy is again mostly infeasible under realistic constraints. On timing, at 300 items MILP is actually faster — about 227 milliseconds versus 4 seconds for GRASP-LS — but it is license-free and anytime, which is what matters for deployment. We also stress-tested a two-by-two of tight-versus-loose budget and high-versus-loose protein: even in the hardest corner GRASP-LS stayed within 7.4% of optimal and feasible in 46 of 48 — and interestingly, high protein, not tight budget, is the main source of difficulty.

### Slide 16 — Sensitivity Analysis: β and γ  (~45s)
> Two sensitivity results. On the left, beta controls the cost–protein trade-off: a higher beta gives more protein but at a higher cost, moving from about 46 grams up to 120. On the right, gamma controls diversity: once gamma is at least 1, repeated items are eliminated — and remarkably, with little or no extra cost; here the cost even dips slightly.

### Slide 17 — The Price of Diversity  (~45s)
> This is our favorite result — the price of diversity. Using Gurobi’s solution pool, we enumerate every solution within epsilon of optimal. At epsilon 0 there’s exactly one optimal meal, but at epsilon 8 there are already 12 distinct on-target meals, costing on average just NT$6.7 more. So instead of always showing the single optimum, we sample from these near-optimal meals — diversity is essentially free.

### Slide 18 — Conclusions: Academic Contributions  (~40s)
> To conclude, on the academic side: we formulated a MILP that integrates promo bundles, personalized nutrition, meal structure, and a tiered diversity penalty; we designed an anytime GRASP-LS that is highly feasible with small optimality gaps — 7.1% and 4.9%; and we validated everything on real data, 488 items, with a working web prototype.

### Slide 19 — Conclusions: Practical Insights  (~35s)
> And on the practical side: simple greedy ranking fails under realistic constraints — it’s zero percent feasible; role tagging makes the recommendation look like an actual meal rather than a pile of nutrients; and diversity is achievable at very low extra cost — with beta giving users a direct handle to trade cost against protein. We also compared against a simulated blind shopper: a random within-budget pick meets all single-meal targets only about 4% of the time, whereas the model hits 100% at a comparable spend — so the value isn't saving money, it's guaranteeing nutrition at the same price.

### Slide 20 — Future Work + Thanks  (~35s)
> For future work, we’d like multi-day planning with restock dynamics, OCR-based in-store product updates, online learning from user feedback, multi-chain integration across 7-11, Hi-Life, and FamilyMart, and stronger local-search neighborhoods to close the gap further. Thank you!

---
*Timing ≈ 13–14 min talk + ~2 min demo. To fit a tighter slot, trim slides 5–7 and 15–17 first; keep the demo (14) and the results headline (13).*
