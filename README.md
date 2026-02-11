# 🎯 DealFinder - Intelligent Ricardo.ch Deal Scanner

**Version 8.0** - AI-Powered Arbitrage Deal Finder for Swiss Online Marketplace

DealFinder automatically scans Ricardo.ch (Swiss auction platform) to identify profitable resale opportunities using AI, web scraping, and market data analysis.

---

## 🌟 Key Features

### 🤖 **Hybrid AI System**

- **Claude AI** (Primary) - Haiku for speed, Sonnet for web search
- **OpenAI GPT-4** (Fallback) - Automatic failover
- **Real Web Search** - Fetches actual new prices from Digitec, Galaxus, Zalando (85-90% success rate)
- **Vision API** - Detects bundles and product quantities from images

### 📊 **Market-Based Pricing**

- Calculates resale prices from **real auction data** (not just AI estimates)
- Trusts auctions with 20+ bids as ground truth
- Variant-specific pricing (e.g., iPhone 128GB vs 256GB)
- Sanity checks prevent unrealistic valuations

### 🎯 **Smart Filtering (v7.2)**

- **Dual-Layer Accessory Detection**:
  - Hardcoded keywords (instant, free)
  - AI-generated keywords (product-specific)
- **Query-Aware**: Searching for "Armband"? Won't filter armbands!
- **Category-Aware**: Fitness "Set" = bundle, not accessory
- **Position-Based**: "Armband für Garmin" (filter) vs "Garmin mit Armband" (keep)
- **Defect Detection**: Filters broken items automatically

### 💰 **Profit Optimization**

- Calculates expected profit after Ricardo fees (10%) and shipping
- Deal scoring system (0-10)
- Strategy recommendations: "Buy Now", "Bid", "Watch", "Skip"
- Cost tracking: Monitors daily AI spending

### 🗄️ **Database & Caching**

- PostgreSQL with auto-migration
- Price history tracking
- Smart caching (7-60 days depending on data type)
- Saves 90%+ on AI costs through intelligent caching

### 📄 **Detail Scraping (v7.0)**

- Scrapes seller ratings, shipping costs, pickup availability
- No AI costs - pure browser automation
- Top 5 deals per run

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.13+**
- **PostgreSQL** database
- **API Keys**:
  - `ANTHROPIC_API_KEY` (Claude AI)
  - `OPENAI_API_KEY` (Optional fallback)

### Installation

```bash
# Clone repository
git clone <your-repo-url>
cd the-deals

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Setup PostgreSQL database
createdb dealfinder
psql dealfinder -c "CREATE USER dealuser WITH PASSWORD 'dealsecret';"
psql dealfinder -c "GRANT ALL PRIVILEGES ON DATABASE dealfinder TO dealuser;"
```

### Configuration

1. **Copy `.env.example` to `.env`** (create if missing):

```env
ANTHROPIC_API_KEY=your_claude_api_key_here
OPENAI_API_KEY=your_openai_api_key_here  # Optional
```

2. **Edit `configs/config.yaml`**:

```yaml
search:
  queries:
    - "iPhone 13"
    - "Garmin Smartwatch"
    - "Tommy Hilfiger"

general:
  max_pages_list: 2 # Pages to scrape per query
  max_listings_per_query: 20 # Listings to evaluate
```

### Run

```bash
python main.py
```

---

## 📋 How It Works

### Pipeline Overview

```
1. Query Analysis (AI, cached 30 days)
   └─> Extracts: category, price range, defect keywords, accessory keywords

2. Web Scraping (Playwright)
   └─> Scrapes Ricardo.ch search results

3. Pre-Filtering (v7.2 - COST SAVER!)
   ├─> Hardcoded accessory detection (query/category-aware)
   ├─> AI accessory keywords
   ├─> Defect keywords
   └─> Exclude terms from config

4. Variant Clustering (AI)
   └─> Groups similar products (e.g., "iPhone 13 128GB" vs "256GB")

5. Market Price Calculation
   └─> Analyzes auction data with bids to determine real market value

6. Variant Info Fetching (AI + Web Search)
   └─> Searches Digitec/Galaxus for new prices
   └─> Checks if item fits in car (for large items)

7. Listing Evaluation (AI + Vision)
   ├─> Bundle detection (vision API if unclear)
   ├─> Profit calculation (resale - purchase - fees)
   ├─> Deal scoring (0-10)
   └─> Strategy recommendation

8. Detail Scraping (Top 5 deals)
   └─> Seller rating, shipping cost, pickup availability

9. Database Storage
   └─> PostgreSQL with price history

10. HTML Report Generation
    └─> Visual overview of all deals
```

### Pricing Philosophy

1. **Auction Data > AI Estimates** (always trust real market data)
2. **More bids = more trust** (20+ bids = fully trusted)
3. **Buy-now ceiling is a CEILING** (not a floor price)
4. **Variant-specific pricing** (each variant has its own reference)
5. **Used items max 70%** of their new price
6. **Premium brands = higher valuations**

---

## 🗂️ Project Structure

```
the-deals/
├── main.py                 # Main pipeline orchestration
├── config.py               # Configuration loader
├── ai_filter.py            # AI evaluation & clustering (2188 lines)
├── query_analyzer.py       # Query analysis with AI
├── db_pg.py                # PostgreSQL database operations
├── market_prices.py        # Market price calculation
├── utils_text.py           # Text utilities (v7.2 smart filtering)
├── utils_time.py           # Time parsing utilities
├── scrapers/
│   ├── ricardo.py          # Ricardo.ch scraper
│   ├── detail_scraper.py   # Detail page scraper
│   └── browser_ctx.py      # Browser context management
├── configs/
│   └── config.yaml         # Main configuration file
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

---

## ⚙️ Configuration Reference

### `configs/config.yaml`

```yaml
general:
  max_pages_list: 2 # Pages to scrape per query
  max_listings_per_query: 20 # Max listings to evaluate
  exclude_terms: # Global exclude keywords
    - "defekt"
    - "kaputt"
  detail_pages_enabled: true # Scrape detail pages?
  max_detail_pages_per_run: 5 # How many detail pages

ai:
  provider: "claude" # "claude" or "openai"
  claude_model_fast: "claude-3-5-haiku-20241022"
  claude_model_web: "claude-sonnet-4-20250514"
  use_ai_vision: true # Enable vision for bundles

  web_search:
    enabled: true # Enable real web search
    preferred_shops:
      - "digitec.ch"
      - "galaxus.ch"

  budget:
    daily_cost_usd_max: 1.50 # Daily spending limit
    daily_vision_calls_max: 100
    daily_web_search_max: 50

cache:
  enabled: true
  clear_on_start: false # Clear caches on startup?
  variant_cache_days: 30
  web_price_cache_days: 60

profit:
  ricardo_fee_percent: 0.10 # Ricardo takes 10%
  shipping_cost_chf: 0.0 # Average shipping cost
  min_profit_threshold: 20.0 # Minimum profit to consider

db:
  clear_on_start: false # Clear DB on startup (testing)
```

---

## 📊 Database Schema

### `listings` Table

Key columns:

- `listing_id` - Ricardo listing ID
- `title`, `description` - Listing content
- `current_price_ricardo` - Current auction price
- `buy_now_price` - Sofortkauf price
- `bids_count` - Number of bids
- `new_price` - New price (from web search)
- `resale_price_est` - Estimated resale value
- `expected_profit` - Calculated profit
- `deal_score` - Score 0-10
- `variant_key` - Product variant identifier
- `recommended_strategy` - "buy_now", "bid", "watch", "skip"
- `market_based_resale` - Used market data? (vs AI estimate)
- `seller_rating` - Seller trustworthiness % (v7.0)
- `shipping_cost` - Shipping cost CHF (v7.0)

### `price_history` Table

Tracks auction price changes over time.

### `market_data` Table

Caches market resale prices per variant (expires after 7 days).

---

## 💡 Usage Tips

### Finding Good Deals

1. **Start with popular brands**: iPhone, Samsung, Garmin, Tommy Hilfiger
2. **Check deal_score > 7**: High-confidence deals
3. **Prefer market_based_resale = true**: Real data beats estimates
4. **Watch auctions with few bids**: Potential to win cheap
5. **Buy-now with high profit**: Instant deals

### Optimizing Costs

- **Enable caching** (saves 90%+ on AI costs)
- **Use pre-filters** (v7.2 filters 60-80% before AI)
- **Set daily budgets** to prevent overspending
- **Limit max_listings_per_query** for testing

### Debugging

- Check `ai_cost_day.txt` for daily spending
- Review logs for filter statistics
- Query database: `SELECT * FROM listings WHERE deal_score > 7 ORDER BY expected_profit DESC;`

---

## 🔧 Development

### Version History

- **v7.2** - Improved accessory filtering (query/category-aware, position-based)
- **v7.1** - Added accessory keyword filtering
- **v7.0** - Claude AI primary, real web search, detail scraping
- **v6.3** - Market-based pricing with sanity checks
- **v6.0** - Market data caching
- **v5.0** - Bundle detection with vision

### Contributing

This is a personal project, but suggestions welcome!

### Testing

```bash
# Enable test mode in config.yaml
db:
  clear_on_start: true  # Clears DB each run

cache:
  clear_on_start: true  # Clears caches each run

# Run with limited scope
general:
  max_pages_list: 1
  max_listings_per_query: 5
```

---

## 📈 Performance

### Typical Run (3 queries, 20 listings each)

- **Scraping**: ~2-3 minutes
- **AI Evaluation**: ~3-5 minutes
- **Total Time**: ~5-8 minutes
- **AI Cost**: $0.10-0.30 USD (with caching)
- **Filter Efficiency**: 60-80% filtered before AI (huge cost savings!)

### Success Rates

- **Web Search (New Prices)**: 85-90% success
- **Market Price Calculation**: 40-60% (depends on auction data)
- **Bundle Detection**: 95%+ accuracy

---

## ⚠️ Limitations

- **Ricardo.ch only** (Swiss marketplace)
- **Requires active internet** for web search
- **AI costs** can add up without caching
- **Playwright browser** needs to stay open during scraping
- **PostgreSQL required** (no SQLite support)

---

## 📝 License

MIT License - See LICENSE file

---

## 🙏 Acknowledgments

- **Claude AI** (Anthropic) - Primary AI engine
- **Playwright** - Browser automation
- **PostgreSQL** - Reliable data storage
- **Ricardo.ch** - Swiss marketplace

---

## 📧 Support

For issues or questions, please open a GitHub issue.

---

**Happy Deal Hunting! 🎯💰**
