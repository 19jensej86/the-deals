# Example Log Output - DealFinder Pipeline Run

**Date:** 2026-01-12 23:00:00  
**Run ID:** 20260112_230000

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 📍 STEP: QUERY_ANALYSIS

## ══════════════════════════════════════════════════════════════════════════════════════

💡 What: Analyzing search queries to understand what products we're looking for
❓ Why: We need to know product categories, typical prices, and common accessories to filter listings intelligently

🔧 Technology: 🤖 AI (LLM) - COST-RELEVANT

💰 COST IMPACT: This step uses AI and causes API costs.

💬 Explanation:
Each search query (like 'Tommy Hilfiger' or 'Garmin smartwatch') is analyzed by
AI. The AI tells us: What category is this? What's a realistic minimum price?
Which accessories are commonly bundled? This helps us filter out junk listings
later.

🤖 AI TRANSPARENCY:
Purpose: Queries are too diverse for hardcoded rules. AI understands context and product knowledge.
Input: 3 search queries (e.g. 'Tommy Hilfiger', 'Garmin smartwatch')
Output: Category, min price, accessory keywords, defect keywords for each query
Fallback: If AI fails, use generic category detection (regex-based)

⏳ Analyzing 3 queries...
✅ All 3 queries analyzed successfully (3)

📊 Result: All 3 queries analyzed successfully
• Queries analyzed: 3
• Cache hits: Cached for 30 days (no cost on re-runs)

⏱️ Duration: 1.2s
✓ Outcome: Query analysis complete - ready to scrape listings
══════════════════════════════════════════════════════════════════════════════════════

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 📍 STEP: SCRAPING

## ══════════════════════════════════════════════════════════════════════════════════════

💡 What: Scraping Ricardo listings for all search queries
❓ Why: We need to collect all available listings to find good deals

🔧 Technology: 📏 Rule-based (Regex/Heuristics) - NO COST

✅ NO COST: This step does NOT use AI.

💬 Explanation:
We visit Ricardo.ch and search for each product. For each listing, we extract:
title, price, end time, image, description. We also apply smart filters to skip
obvious junk (accessories, defects, excluded terms). This step does NOT use AI -
it's pure web scraping with rule-based filtering.

⏳ Scraping query: 'Tommy Hilfiger'
✅ Scraped 'Tommy Hilfiger' (8)
⚙️ Logic: Pre-filtered 4 listings (accessories, defects, excluded terms)
⏳ Scraping query: 'Garmin smartwatch'
✅ Scraped 'Garmin smartwatch' (8)
⚙️ Logic: Pre-filtered 1 listings (accessories, defects, excluded terms)
⏳ Scraping query: 'Hantelscheiben'
✅ Scraped 'Hantelscheiben' (8)
⚙️ Logic: Pre-filtered 0 listings (accessories, defects, excluded terms)

📊 Result: Scraped 24 listings from 3 queries
• Total scraped: 29
• Passed filters: 24
• Filtered out: 5

⏱️ Duration: 45.3s
✓ Outcome: Scraping complete - 24 listings ready for processing
══════════════════════════════════════════════════════════════════════════════════════

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 📍 STEP: AI_TITLE_NORMALIZATION

## ══════════════════════════════════════════════════════════════════════════════════════

💡 What: Normalizing listing titles to extract clean product names
❓ Why: Listing titles contain noise (colors, sizes, conditions) that prevent accurate price lookups. We need clean product names for web searches.

🔧 Technology: 🤖 AI (LLM) - COST-RELEVANT

💰 COST IMPACT: This step uses AI and causes API costs.

💬 Explanation:
Listing titles are messy. Example: 'Tommy Hilfiger Winter Gr.L blau NEU'. We
need just 'Tommy Hilfiger Winter' to find prices online. We also detect bundles
(e.g. '2x iPhone') and split them into individual products. AI is used because
titles are multilingual (DE/FR/EN) and have too many edge cases for simple
rules.

🤖 AI TRANSPARENCY:
Purpose: Titles are too complex for regex: multilingual, unstructured, many edge cases. AI understands context.
Input: All 24 listing titles from all queries (batched for cost efficiency)
Output: Clean product names + quantities (e.g. 'Tommy Hilfiger Winter', qty=1)
Fallback: If AI fails: regex-based cleanup (removes common noise patterns)

⏳ Sending 24 titles to AI (1 global batch call)...
⚙️ Logic: Cost optimization: 1 AI call for ALL titles instead of 3 separate calls
✅ AI normalized 24 titles (24)
⚙️ Logic: Post-AI cleanup: Regex safety net removes any size/color/condition words AI missed

📊 Result: Extracted 21 unique products from 24 listings
• Raw listings: 24
• Unique products: 21
• Deduplication rate: 13%
• Invalid listings: 0

⏱️ Duration: 3.8s
✓ Outcome: Title normalization complete - 21 unique products identified
══════════════════════════════════════════════════════════════════════════════════════

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 📍 STEP: PRICE_FETCHING

## ══════════════════════════════════════════════════════════════════════════════════════

💡 What: Finding market prices for all unique products
❓ Why: We need to know what each product costs new/used to calculate profit potential

🔧 Technology: 🤖 AI (LLM) - COST-RELEVANT, 🌐 Web Search - COST-RELEVANT, 💾 Database

💰 COST IMPACT: This step uses AI and causes API costs.

💬 Explanation:
For each unique product, we need to find: (1) New price from web shops, (2) Used
resale price from Ricardo auctions. We use 3 sources in priority order: Web
search (most accurate), Market data from past auctions (good for popular items),
AI estimation (fallback). Web search uses AI with web access - this is the most
expensive step but gives best results.

🤖 AI TRANSPARENCY:
Purpose: Web shops have different formats and structures. AI with web search can understand any shop layout and extract prices reliably.
Input: 21 unique product names (e.g. 'Garmin Fenix 7', 'Tommy Hilfiger Winter')
Output: New price + source (e.g. '399 CHF from Galaxus')
Fallback: If web search fails: AI estimates price based on product knowledge

✅ Market prices calculated (3)
⚙️ Logic: Market prices come from past Ricardo auctions with bids (free - no AI cost)
⏳ Fetching new prices for 21 unique products via web search...
⚙️ Logic: Web search uses AI with web access - this is the most expensive operation

📊 Result: Price fetching complete for 21 products
• Market prices: 3
• Web search attempts: 21
• Web search success: 6 (29%)
• AI fallback used: 15

⏱️ Duration: 125.4s
✓ Outcome: Price data ready - 6 web prices + 3 market prices
══════════════════════════════════════════════════════════════════════════════════════

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 📍 STEP: DEAL_EVALUATION

## ══════════════════════════════════════════════════════════════════════════════════════

💡 What: Evaluating each listing to calculate profit and recommend strategy
❓ Why: We need to decide which listings are good deals worth buying

🔧 Technology: 🤖 AI (LLM) - COST-RELEVANT, 💾 Database

💰 COST IMPACT: This step uses AI and causes API costs.

💬 Explanation:
For each listing, we calculate: Expected profit = (Resale price - Purchase price

- Fees). We also predict the final auction price and recommend a strategy: Buy
  Now (great deal), Bid (good deal), Watch (maybe), or Skip (not profitable). AI
  is used to understand listing quality, detect defects, and make smart
  predictions.

🤖 AI TRANSPARENCY:
Purpose: Listings have complex factors: condition, seller rating, shipping, bundle logic. AI can weigh all factors intelligently.
Input: 24 listings with prices, descriptions, images
Output: Profit calculation, strategy recommendation, deal score
Fallback: If AI fails: use simple profit formula without quality adjustments

📋 Evaluating 8 listings for 'Tommy Hilfiger'
🔥 Tommy Hilfiger Winter Gr.L... | Profit: 55 CHF
⏭️ Tommy Hilfiger Strickpullover (L)... | Profit: -54 CHF
⏭️ Lot de 2 boxershortTommy Hilfiger, taille S... | Profit: -4 CHF

📋 Evaluating 8 listings for 'Garmin smartwatch'
🔥 Garmin Fenix 3. Smartwatch. Gebraucht. Funktionier... | Profit: 142 CHF
⏭️ Garmin Fenix 7 - Solar... | Profit: -94 CHF
⏭️ Garmin Vivosmart 5, NEU Garantieaustausch... | Profit: -39 CHF

📋 Evaluating 8 listings for 'Hantelscheiben'
👀 Hantelscheiben Set, Guss, 6 Stk. - Ideal für dein ... | Profit: 39 CHF
⏭️ Hantelscheiben Set Crane, Gusseisen, Total 8kg... | Profit: 5 CHF
⏭️ Kettlebell verstellbar, Kugelhantel, Adjustable, H... | Profit: -69 CHF

📊 Result: Evaluated 24 listings - found 2 profitable deals
• Total evaluated: 24
• Profitable deals: 2
• Strategies: {'skip': 19, 'buy_now': 2, 'watch': 3}

⏱️ Duration: 18.7s
✓ Outcome: Evaluation complete - 2 deals worth pursuing
══════════════════════════════════════════════════════════════════════════════════════

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 📍 STEP: DETAIL_SCRAPING

## ══════════════════════════════════════════════════════════════════════════════════════

💡 What: Scraping detail pages for top 4 deals
❓ Why: Detail pages contain extra info: seller rating, shipping cost, exact location - helps make better buying decisions

🔧 Technology: 📏 Rule-based (Regex/Heuristics) - NO COST

✅ NO COST: This step does NOT use AI.

💬 Explanation:
We visit the actual listing pages (not just search results) to extract
additional details. This step does NOT use AI - it's pure web scraping with DOM
selectors. We only scrape the most profitable deals to save time.

🔍 Scraping 4 detail pages (top by profit)...

[1/4] Garmin Fenix 3. Smartwatch. Gebraucht. F... (Profit: 142 CHF)
✅ Got: Rating=None%, Shipping=9.0 CHF, Pickup=True

[2/4] Tommy Hilfiger Winter Gr.L... (Profit: 55 CHF)
✅ Got: Rating=None%, Shipping=9.0 CHF, Pickup=True

[3/4] Hantelscheiben Set, Guss, 6 Stk. - Ideal... (Profit: 39 CHF)
✅ Got: Rating=None%, Shipping=21.0 CHF, Pickup=True

[4/4] Hantelscheiben Set Crane, Gusseisen, Tot... (Profit: 5 CHF)
✅ Got: Rating=None%, Shipping=21.0 CHF, Pickup=True

✓ VERIFIED: 4 detail pages scraped successfully
Evidence: Database fields populated: location, shipping_cost, pickup_available

📊 Result: Detail scraping complete
• Attempted: 4
• Successful: 4
• Failed: 0
• Success rate: 100%

⏱️ Duration: 28.3s
✓ Outcome: Detail scraping complete - 4/4 successful
══════════════════════════════════════════════════════════════════════════════════════

---

## ══════════════════════════════════════════════════════════════════════════════════════

## 💰 COST SUMMARY

## ══════════════════════════════════════════════════════════════════════════════════════

📊 API Usage:
• AI Calls: 8
• Web Searches: 21
• Total Cost: $1.4180 USD

📈 Cost Breakdown:
• Query Analysis: $0.0020
• Title Normalization: $0.0050
• Web Price Search: $1.2053
• Deal Evaluation: $0.1418

✅ Steps that used AI (cost-relevant):
• Query Analysis
• Title Normalization
• Web Price Search
• Deal Evaluation

✅ Steps that did NOT use AI (free):
• Scraping (Playwright)
• Regex-based filtering
• Database operations
• Detail page scraping

══════════════════════════════════════════════════════════════════════════════════════

📅 Date: 2026-01-12
📊 Today total: $3.1890 USD

✅ Pipeline completed successfully!
