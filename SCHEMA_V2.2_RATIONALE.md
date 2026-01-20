# Schema v2.2 FINAL - Rationale & Migration Guide

## Why v2.2 is Better Than v2.1

### Summary of Changes

| Change | Problem Solved | Benefit |
|--------|----------------|---------|
| **1. USER_ACTIONS table** | No way to track user decisions across runs | UI workflow support (buy/watch/purchased) |
| **2. PRODUCT_ALIASES table** | variant_key evolution breaks product identity | Stable product grouping despite AI changes |
| **3. Data type consistency** | Mixed types (TEXT run_id, TIMESTAMP) | Production-grade type safety |
| **4. Bundle model cleanup** | No orphan bundle_id references | Clean parent-child relationship |
| **5. Production views** | Manual joins for every query | One-line dashboard queries |

---

## 1. USER_ACTIONS: UI Workflow Support

### Problem in v2.1
Deals are **immutable snapshots per run**. But users need to:
- Mark listings as "watch" or "buy now"
- Add notes: "Wait until price drops below 100 CHF"
- Track purchased items
- Ignore listings permanently

**Without user_actions**: Every run creates new deal rows, losing user context.

### Solution: Persistent User State

```sql
CREATE TABLE user_actions (
    listing_id      BIGINT,              -- Stable across runs
    product_id      INTEGER,             -- Optional: apply to all listings of product
    action          TEXT,                -- 'buy', 'watch', 'ignore', 'purchased', 'archived'
    notes           TEXT,
    tags            TEXT[]
);
```

### UI Query Pattern

**Dashboard with user overlay**:
```sql
SELECT * FROM v_latest_deals;
-- Returns deals with user_action, user_notes, user_tags columns
```

**Example output**:
| product_name | expected_profit | strategy | user_action | user_notes |
|--------------|-----------------|----------|-------------|------------|
| iPhone 12 mini | 185 CHF | watch | watch | Wait for <100 CHF |
| AirPods Pro | 86 CHF | buy_now | NULL | NULL |

**Workflow**:
1. User sees deal in dashboard
2. Clicks "Add to Watchlist" → `INSERT INTO user_actions (listing_id, action) VALUES (123, 'watch')`
3. Next run: Same listing appears with `user_action = 'watch'` overlay
4. User purchases → `UPDATE user_actions SET action = 'purchased'`
5. Dashboard filters out purchased items automatically

---

## 2. PRODUCT_ALIASES: Identity Hardening

### Problem in v2.1
AI extraction generates variant_keys that may evolve:

**Run 1**: `apple_iphone_12_mini_128GB` (uppercase GB)  
**Run 2**: `apple_iphone_12_mini_128gb` (lowercase gb)

**Result**: Two separate product records, fragmented analytics.

### Solution: Alias Resolution

```sql
CREATE TABLE product_aliases (
    product_id      INTEGER,
    alias_key       TEXT UNIQUE          -- Old or alternative variant_key
);
```

**Migration workflow**:
1. Improve extraction prompt → new normalization
2. Old variant_key: `apple_iphone_12_mini_128GB`
3. New variant_key: `apple_iphone_12_mini_128gb`
4. Add alias: `INSERT INTO product_aliases (product_id, alias_key) VALUES (42, 'apple_iphone_12_mini_128GB')`
5. Both keys now resolve to product 42

**Function support**:
```sql
SELECT resolve_product('apple_iphone_12_mini_128GB');  -- Returns 42
SELECT resolve_product('apple_iphone_12_mini_128gb');  -- Returns 42
```

**Benefit**: Product analytics remain stable despite extraction evolution.

---

## 3. Data Type Consistency

### Changes Applied

| Field | v2.1 | v2.2 | Reason |
|-------|------|------|--------|
| `run_id` | TEXT | UUID | Proper type, prevents collisions |
| Timestamps | TIMESTAMP | TIMESTAMPTZ | Timezone-aware |
| Money | NUMERIC | NUMERIC(12,2) | Explicit precision for CHF |
| `deal_score` | NUMERIC | NUMERIC(3,1) | 1.0-10.0 range |
| `ai_cost_usd` | NUMERIC | NUMERIC(10,4) | 4 decimal places for cents |

### CHECK Constraints Added

```sql
-- Non-negative prices
CONSTRAINT chk_buy_now_price CHECK (buy_now_price IS NULL OR buy_now_price >= 0)

-- Valid score range
CONSTRAINT chk_deal_score CHECK (deal_score >= 1.0 AND deal_score <= 10.0)

-- Valid seller rating
CONSTRAINT chk_seller_rating CHECK (seller_rating IS NULL OR (seller_rating >= 0 AND seller_rating <= 100))
```

**Benefit**: Database enforces business rules, prevents invalid data.

---

## 4. Bundle Model Cleanup

### v2.1 Issue
`bundle_items.bundle_id` referenced `deals.bundle_id`, but:
- Deals are for **single products only**
- Bundles are **separate entities**
- `bundle_id` in deals was an orphan concept

### v2.2 Solution

**Clean separation**:
```
deals        → Single products only (NO bundle_id field)
bundles      → Bundle evaluations (first-class entity)
bundle_items → References bundles.id (NOT deals)
```

**Data model**:
```
bundles (1) ──< bundle_items (N)
   ↓
listings (1)
```

**Benefit**: No orphan foreign keys, semantically correct.

---

## 5. Production-Grade Views

### v_latest_deals
All deals from latest run with user action overlay.

**Use case**: Main dashboard

**Columns**:
- Deal evaluation (profit, score, strategy)
- Product info (name, brand, category)
- Listing info (url, image, end_time)
- **User overlay** (user_action, user_notes, user_tags)
- Computed (hours_remaining, profit_margin_pct)

### v_dashboard
Unified deals + bundles for main UI.

**Use case**: Single query for entire dashboard

**Query**:
```sql
SELECT * FROM v_dashboard 
WHERE expected_profit > 0 
ORDER BY deal_score DESC 
LIMIT 20;
```

### v_action_required
Items needing immediate action, excluding already handled.

**Use case**: "Buy Now" tab

**Filter logic**:
- `strategy IN ('buy_now', 'bid_now')`
- `end_time > NOW()` (not expired)
- `user_action NOT IN ('purchased', 'archived', 'ignore')`

### v_watchlist
Items user is actively watching.

**Use case**: "Watchlist" tab

### v_purchased
Items user has marked as purchased.

**Use case**: Purchase history

---

## Example Queries

### 1. Top Deals with User Action Overlay

```sql
SELECT 
    product_name,
    expected_profit,
    deal_score,
    strategy,
    user_action,
    user_notes,
    hours_remaining
FROM v_latest_deals
WHERE expected_profit > 20
  AND user_action IS NULL  -- Not yet handled
ORDER BY deal_score DESC
LIMIT 10;
```

**Output**:
| product_name | expected_profit | deal_score | strategy | user_action | hours_remaining |
|--------------|-----------------|------------|----------|-------------|-----------------|
| iPhone 12 mini | 222 CHF | 9.0 | watch | NULL | 83.2 |
| AirPods Pro 2 | 86 CHF | 9.5 | buy_now | NULL | 1813.4 |

---

### 2. All Deals for Product Family

```sql
SELECT 
    product_name,
    expected_profit,
    deal_score,
    cost_estimate,
    market_value,
    url
FROM v_latest_deals
WHERE base_product_key = 'apple_iphone_12_mini'
ORDER BY expected_profit DESC;
```

**Use case**: "Show me all iPhone 12 mini deals"

**Benefit**: `base_product_key` groups all variants (64GB, 128GB, colors).

---

### 3. Purchased Items List

```sql
SELECT 
    product_name,
    expected_profit,
    cost_estimate,
    purchase_date,
    purchase_notes,
    url
FROM v_purchased
ORDER BY purchase_date DESC;
```

**Output**:
| product_name | expected_profit | cost_estimate | purchase_date | purchase_notes |
|--------------|-----------------|---------------|---------------|----------------|
| AirPods Pro 2 | 86 CHF | 49 CHF | 2026-01-20 | Bought via Buy Now |

---

### 4. Mark Listing as Purchased

```sql
SELECT set_user_action(
    123,                    -- listing_id
    'purchased',            -- action
    'Bought for 50 CHF'     -- notes
);
```

**Effect**: 
- Listing disappears from `v_action_required`
- Appears in `v_purchased`
- User notes saved for reference

---

### 5. Product Performance Over Time

```sql
SELECT 
    p.display_name,
    r.started_at::DATE AS run_date,
    COUNT(*) AS deal_count,
    AVG(d.expected_profit) AS avg_profit,
    MAX(d.expected_profit) AS best_profit
FROM deals d
JOIN products p ON d.product_id = p.id
JOIN runs r ON d.run_id = r.id
WHERE p.base_product_key = 'apple_iphone_12_mini'
GROUP BY p.display_name, r.started_at::DATE
ORDER BY run_date DESC;
```

**Use case**: "How has iPhone 12 mini profitability changed over time?"

---

### 6. Handle Variant Key Migration

**Scenario**: Extraction logic improved, now generates lowercase `gb` instead of `GB`.

**Before migration**:
```sql
-- Old variant_key: apple_iphone_12_mini_128GB
-- New variant_key: apple_iphone_12_mini_128gb
-- Result: Two separate products!
```

**Migration**:
```sql
-- 1. Find product with old variant_key
SELECT id FROM products WHERE variant_key = 'apple_iphone_12_mini_128GB';
-- Returns: 42

-- 2. Update canonical variant_key
UPDATE products SET variant_key = 'apple_iphone_12_mini_128gb' WHERE id = 42;

-- 3. Add old variant_key as alias
SELECT add_product_alias(42, 'apple_iphone_12_mini_128GB');

-- 4. Now both resolve to product 42
SELECT resolve_product('apple_iphone_12_mini_128GB');  -- 42
SELECT resolve_product('apple_iphone_12_mini_128gb');  -- 42
```

**Benefit**: Historical data preserved, analytics unbroken.

---

## Migration from v2.1 to v2.2

### Schema Changes

1. **Add UUID extension**: `CREATE EXTENSION IF NOT EXISTS "uuid-ossp";`
2. **Change run_id type**: TEXT → UUID (requires data migration if existing data)
3. **Add new tables**: `user_actions`, `product_aliases`
4. **Update data types**: TIMESTAMP → TIMESTAMPTZ, NUMERIC → NUMERIC(12,2)
5. **Add CHECK constraints**: Price validation, score ranges
6. **Remove bundle_id from deals**: Bundles are separate

### Data Migration (if migrating from v2.1)

```sql
-- 1. Backup existing data
CREATE TABLE deals_backup AS SELECT * FROM deals;

-- 2. Drop old tables
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

-- 3. Run schema_v2.2_FINAL.sql
\i schema_v2.2_FINAL.sql

-- 4. Migrate data (if needed)
-- Note: Since we're starting fresh, no migration needed
```

---

## Production Readiness Checklist

- [x] UUID for run_id (prevents collisions)
- [x] TIMESTAMPTZ for all timestamps (timezone-aware)
- [x] NUMERIC(12,2) for money (explicit precision)
- [x] CHECK constraints (data validation)
- [x] User action persistence (UI workflow)
- [x] Product alias support (identity stability)
- [x] Clean bundle model (no orphans)
- [x] Production views (one-line queries)
- [x] Helper functions (get_or_create_product, resolve_product, set_user_action)
- [x] Comprehensive indexes (query performance)
- [x] Foreign key cascades (referential integrity)
- [x] Table comments (documentation)

---

## Performance Considerations

### Indexes Created

**Products**:
- `variant_key` (UNIQUE)
- `base_product_key` (grouping queries)
- `brand`, `category` (filtering)

**Listings**:
- `run_id` (run-based queries)
- `product_id` (product-based queries)
- `end_time` (time-based filtering)
- `(platform, source_id)` (UNIQUE, deduplication)

**Deals**:
- `run_id` (latest run queries)
- `deal_score DESC` (top deals)
- `expected_profit DESC` (sorting)
- `strategy` (filtering)
- `(listing_id, run_id)` (UNIQUE, one eval per listing per run)

**User Actions**:
- `listing_id` (overlay queries)
- `product_id` (product-level actions)
- `action` (filtering by status)
- `tags` (GIN index for array search)

### Query Optimization

**Views use indexes**:
- `v_latest_deals` filters by `run_id` (indexed)
- `v_action_required` filters by `strategy` (indexed)
- `v_watchlist` filters by `user_action` (indexed)

**Computed columns**:
- `hours_remaining` = computed at query time (not stored)
- `profit_margin_pct` = computed at query time (not stored)

**Benefit**: No stale derived data, always accurate.

---

## Summary

**v2.2 is production-ready** because it:

1. **Supports real UI workflows** (user actions, watchlist, purchase tracking)
2. **Handles product identity evolution** (aliases for variant_key changes)
3. **Enforces data integrity** (CHECK constraints, proper types)
4. **Provides clean semantics** (bundles separate from deals)
5. **Enables one-line queries** (production views)

**This schema is boring, obvious, and powerful.**
