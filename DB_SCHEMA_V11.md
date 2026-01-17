# 📦 Database Schema v11 - Normalized "One Product = One Row"

**Version:** v11.0  
**Principle:** *One product = one row, even in bundles. Audit trail for all pricing.*

---

## 🎯 DESIGN GOALS

1. **One product per row** - Each physical product/component gets its own row
2. **Bundle support** - Components grouped via `product_group_id`
3. **Pricing audit trail** - Full `web_sources` JSONB for transparency
4. **Run isolation** - Each pipeline run is isolated and queryable
5. **No false data** - `price_source` constraint prevents 'unknown'

---

## 📊 SCHEMA OVERVIEW

```
┌─────────────┐
│    runs     │  Pipeline executions
├─────────────┤
│ run_id (PK) │
│ created_at  │
│ status      │
│ config_json │
└──────┬──────┘
       │
       │ 1:N
       ▼
┌─────────────────┐
│   listings_v2   │  Original Ricardo listings
├─────────────────┤
│ id (PK)         │
│ run_id (FK)     │
│ listing_id      │
│ title, url      │
│ current_price   │
│ buy_now_price   │
└────────┬────────┘
         │
         │ 1:N (bundles have N products)
         ▼
┌─────────────────┐
│    products     │  ONE ROW PER PRODUCT
├─────────────────┤
│ id (PK)         │
│ run_id (FK)     │
│ listing_row_id  │
│ product_group_id│ ← Groups bundle components
│ cleaned_name    │
│ quantity        │
│ specs (JSONB)   │
└────────┬────────┘
         │
         │ 1:1 (pricing per product)
         ▼
┌─────────────────┐
│    pricing      │  Pricing with audit trail
├─────────────────┤
│ id (PK)         │
│ product_id (FK) │
│ new_price_total │
│ new_price_unit  │
│ price_source    │ ← CONSTRAINED enum
│ web_sources     │ ← FULL AUDIT TRAIL
│ deal_score      │
│ expected_profit │
└─────────────────┘
```

---

## 📋 TABLE DEFINITIONS

### **runs** - Pipeline Executions

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | Unique run ID (e.g., "20260117_180000") |
| `created_at` | TIMESTAMP | When run started |
| `config_hash` | TEXT | MD5 hash of config (for dedup) |
| `config_json` | JSONB | Full config snapshot |
| `status` | TEXT | 'running', 'completed', 'failed' |
| `completed_at` | TIMESTAMP | When run finished |
| `total_listings` | INTEGER | Summary stat |
| `total_products` | INTEGER | Summary stat |
| `total_profitable` | INTEGER | Summary stat |

---

### **listings_v2** - Original Ricardo Listings

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | Internal row ID |
| `run_id` | TEXT FK | Link to runs.run_id |
| `platform` | TEXT | 'ricardo' |
| `listing_id` | TEXT | Original Ricardo ID |
| `title` | TEXT | Listing title |
| `current_price` | NUMERIC | Current auction price |
| `buy_now_price` | NUMERIC | Buy-now price (if exists) |
| `bids_count` | INTEGER | Number of bids |
| `end_time` | TIMESTAMP | Auction end time |
| `location` | TEXT | Seller location |
| `url` | TEXT | Listing URL |
| `raw_payload` | JSONB | Full scraped data (debug) |

**Constraint:** `UNIQUE (run_id, platform, listing_id)`

---

### **products** - One Row Per Product

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | Internal row ID |
| `run_id` | TEXT FK | Link to runs.run_id |
| `listing_row_id` | BIGINT FK | Link to listings_v2.id |
| `product_group_id` | TEXT | Groups bundle components (NULL for single) |
| `is_group_root` | BOOLEAN | True if bundle root product |
| `product_type` | TEXT | e.g., "Hantelscheibe" |
| `brand` | TEXT | e.g., "ATX" |
| `model` | TEXT | e.g., "Olympic Bumper" |
| `cleaned_name` | TEXT NOT NULL | Stable name for pricing lookup |
| `specs` | JSONB | `{"weight_kg": 10, "diameter_mm": 50}` |
| `quantity` | INTEGER NOT NULL | Number of this product (≥1) |
| `extraction_source` | TEXT | 'query_agnostic', 'detail', 'vision' |
| `extraction_confidence` | NUMERIC | 0.0-1.0 |
| `websearch_query` | TEXT | Query used for web search |

**Constraint:** `CHECK (quantity >= 1)`

---

### **pricing** - Pricing Data Per Product

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | Internal row ID |
| `product_id` | BIGINT FK | Link to products.id |
| `run_id` | TEXT FK | Link to runs.run_id |
| `new_price_total` | NUMERIC | Total price for quantity |
| `new_price_unit` | NUMERIC | Price per unit (if derivable) |
| `resale_price_est_total` | NUMERIC | Estimated resale for quantity |
| `resale_price_unit` | NUMERIC | Resale per unit |
| `price_source` | TEXT NOT NULL | **CONSTRAINED ENUM** (see below) |
| `web_sources` | JSONB | **FULL AUDIT TRAIL** |
| `market_sample_size` | INTEGER | Number of price sources |
| `market_based` | BOOLEAN | True if web-sourced |
| `confidence` | NUMERIC | 0.0-1.0 |
| `expected_profit` | NUMERIC | Calculated profit |
| `deal_score` | NUMERIC | 0-100 score |
| `recommended_strategy` | TEXT | 'buy_now', 'bid', 'watch', 'skip' |
| `strategy_reason` | TEXT | Human-readable reason |
| `market_value` | NUMERIC | Market reference value |
| `buy_now_ceiling` | NUMERIC | Max we'd pay |

**Constraint:** `price_source` must be one of:
- `web_median` - Median of ≥2 web prices
- `web_single` - Single web source
- `web_median_qty_adjusted` - Median with quantity derivation
- `ai_estimate` - AI fallback
- `query_baseline` - Category baseline
- `buy_now_fallback` - From buy-now price
- `bundle_aggregate` - Sum of components
- `market_auction` - From Ricardo auctions
- `no_price` - No price available (better than false data!)

---

## 🔍 WEB_SOURCES AUDIT TRAIL FORMAT

```json
[
  {
    "shop": "Digitec",
    "price": 49.90,
    "url": "https://digitec.ch/...",
    "snippet": "ATX Bumper 2 × 5 kg",
    "qty_in_shop": 2,
    "computed_unit_price": 24.95,
    "included_in_median": true
  },
  {
    "shop": "Galaxus",
    "price": 52.00,
    "url": "https://galaxus.ch/...",
    "snippet": "ATX Bumper 5kg single",
    "qty_in_shop": 1,
    "computed_unit_price": 52.00,
    "included_in_median": true
  },
  {
    "shop": "Decathlon",
    "price": 19.90,
    "url": "https://decathlon.ch/...",
    "snippet": "Bumper 5kg AKTION",
    "qty_in_shop": 1,
    "computed_unit_price": 19.90,
    "included_in_median": false,
    "excluded_reason": "outlier_below_40pct"
  }
]
```

**Key Fields:**
- `qty_in_shop`: Quantity in shop listing (for "2 × 5kg" = 2)
- `computed_unit_price`: Derived unit price (shop_price / qty_in_shop)
- `included_in_median`: Whether used in final median
- `excluded_reason`: Why excluded (outlier, mismatch, etc.)

---

## ✅ VERIFICATION QUERIES

### **1. Products per listing (should be ≥1)**
```sql
SELECT platform, listing_id, COUNT(*) AS product_count
FROM products p
JOIN listings_v2 l ON p.listing_row_id = l.id
GROUP BY platform, listing_id
ORDER BY product_count DESC;
```

### **2. Bundle groups (multiple products per group)**
```sql
SELECT product_group_id, COUNT(*) AS components
FROM products
WHERE product_group_id IS NOT NULL
GROUP BY product_group_id
HAVING COUNT(*) > 1
ORDER BY components DESC;
```

### **3. Quantity validation (no zeros/nulls)**
```sql
SELECT COUNT(*) AS invalid_quantity
FROM products
WHERE quantity IS NULL OR quantity < 1;
-- Expected: 0
```

### **4. Price source distribution**
```sql
SELECT price_source, COUNT(*) AS count,
       ROUND(AVG(market_sample_size), 1) AS avg_samples
FROM pricing
GROUP BY price_source
ORDER BY count DESC;
```

### **5. Reject 'unknown' sources (should be 0)**
```sql
SELECT COUNT(*) AS unknown_sources
FROM pricing
WHERE price_source = 'unknown';
-- Expected: 0 (constraint prevents this)
```

### **6. Unit vs total price sanity**
```sql
SELECT COUNT(*) AS invalid_unit_total
FROM pricing
WHERE new_price_unit IS NOT NULL
  AND new_price_total IS NOT NULL
  AND new_price_total < new_price_unit;
-- Expected: 0
```

### **7. Web median sample sizes**
```sql
SELECT COUNT(*) AS weak_medians
FROM pricing
WHERE price_source LIKE 'web_median%'
  AND market_sample_size < 2;
-- Expected: 0
```

### **8. Top deals query**
```sql
SELECT 
    p.cleaned_name,
    p.quantity,
    l.title,
    l.current_price,
    pr.new_price_total,
    pr.resale_price_est_total,
    pr.expected_profit,
    pr.deal_score,
    pr.recommended_strategy,
    pr.price_source
FROM products p
JOIN listings_v2 l ON p.listing_row_id = l.id
JOIN pricing pr ON pr.product_id = p.id
WHERE pr.expected_profit > 0
ORDER BY pr.deal_score DESC NULLS LAST
LIMIT 20;
```

### **9. Bundle profit aggregation**
```sql
SELECT 
    product_group_id,
    COUNT(*) AS components,
    SUM(pr.new_price_total) AS total_new_price,
    SUM(pr.resale_price_est_total) AS total_resale,
    SUM(pr.expected_profit) AS total_profit
FROM products p
JOIN pricing pr ON pr.product_id = p.id
WHERE product_group_id IS NOT NULL
GROUP BY product_group_id
ORDER BY total_profit DESC;
```

### **10. Run summary**
```sql
SELECT 
    r.run_id,
    r.status,
    r.created_at,
    COUNT(DISTINCT l.id) AS listings,
    COUNT(DISTINCT p.id) AS products,
    COUNT(DISTINCT CASE WHEN pr.expected_profit > 0 THEN p.id END) AS profitable
FROM runs r
LEFT JOIN listings_v2 l ON l.run_id = r.run_id
LEFT JOIN products p ON p.run_id = r.run_id
LEFT JOIN pricing pr ON pr.run_id = r.run_id
GROUP BY r.run_id, r.status, r.created_at
ORDER BY r.created_at DESC;
```

---

## 🔧 USAGE IN CODE

### **Initialize Schema**
```python
from db_pg import get_conn, ensure_schema_v2, insert_run

conn = get_conn(cfg.pg)

# Testing mode: reset tables
ensure_schema_v2(conn, reset=True, run_id=run_id)

# Production: create if not exists
ensure_schema_v2(conn, reset=False, run_id=run_id)

# Start a run
insert_run(conn, run_id, config_json=cfg_dict)
```

### **Insert Listing + Products + Pricing**
```python
from db_pg import (
    insert_listing_v2, 
    insert_products_batch, 
    insert_pricing
)

# 1. Insert listing
listing_row_id = insert_listing_v2(conn, run_id, {
    "listing_id": "12345",
    "title": "ATX Bumper Set 2×5kg + 2×10kg",
    "current_price": 80.0,
    "buy_now_price": 120.0,
    ...
})

# 2. Insert products (bundle = multiple)
products = [
    {"cleaned_name": "ATX Bumper 5kg", "quantity": 2, "specs": {"weight_kg": 5}},
    {"cleaned_name": "ATX Bumper 10kg", "quantity": 2, "specs": {"weight_kg": 10}},
]
product_ids = insert_products_batch(conn, run_id, listing_row_id, products)

# 3. Insert pricing per product
for product_id in product_ids:
    insert_pricing(conn, run_id, product_id, {
        "new_price_total": 45.0,
        "new_price_unit": 22.5,
        "price_source": "web_median",
        "market_sample_size": 3,
        "web_sources": [...],  # Full audit trail
        "expected_profit": 15.0,
        "deal_score": 72.5,
    })
```

### **Query Products**
```python
from db_pg import get_products_with_pricing, export_products_json

# Get top deals
deals = get_products_with_pricing(conn, run_id=run_id, min_score=6.0)

# Export to file
export_products_json(conn, run_id, "last_run_products.json")
```

---

## 🚫 FORBIDDEN PATTERNS

1. **NO `price_source = 'unknown'`** - Constraint prevents this
2. **NO `quantity = 0`** - Constraint prevents this
3. **NO false prices** - Use `no_price` instead
4. **NO hallucinated qty derivation** - Only if explicit in shop text

---

## 💡 KEY INSIGHTS

1. **Bundles are just grouped products** - No special bundle table needed
2. **Pricing is per product** - Enables component-level analysis
3. **web_sources is the audit trail** - Every price decision is traceable
4. **quantity × unit = total** - Semantic consistency
5. **run_id isolates data** - Easy to compare runs or reset

---

## 📈 MIGRATION PATH

The old `listings` table is kept for backward compatibility. New code should use:
- `listings_v2` instead of `listings`
- `products` for per-product data
- `pricing` for pricing data

Eventually, the old `listings` table can be deprecated once all code is migrated.
