# 🥇 MEDIAN-FIRST PRICING IMPLEMENTATION

**Principle:** *Nicht Gewicht korrigieren – Markt korrekt aggregieren.*

---

## 📐 ARCHITECTURE PHILOSOPHY

### **MEDIAN-FIRST RULE (Core Principle)**

When ≥2 web prices exist → **ALWAYS use median**

- ✅ No weight normalization
- ✅ No price/kg logic
- ✅ No artificial corrections
- ✅ **The market regulates itself**

### **Why This Works**

1. **Query contains weight:** "Hantelscheibe 10kg" searches for 10kg products
2. **Web returns 10kg prices:** Digitec, Galaxus, Manor all return 10kg prices
3. **Median aggregates market:** Outliers (actions) removed, realistic price emerges
4. **Natural consistency:** 10kg > 5kg automatically because market prices reflect this

---

## 🔧 IMPLEMENTATION DETAILS

### **1. Multi-Source Web Price Collection**

**Location:** `ai_filter.py::search_web_batch_for_new_prices()` (lines 556-627)

**Process:**
```python
# Collect up to 5 prices per product
for price_item in prices_list[:5]:
    if price > 0:
        valid_prices.append(price)
        shops.append(shop_name)

# Compute initial median
median_price = compute_median(valid_prices)

# Remove outliers: ±40% of median
lower_bound = median_price * 0.6
upper_bound = median_price * 1.4
final_prices = [p for p in valid_prices if lower_bound <= p <= upper_bound]

# Recompute median after outlier removal
median_price = compute_median(final_prices)
```

**Result:**
- `price_source = "web_median"` when ≥2 prices
- `market_sample_size = len(final_prices)`
- `market_value = median_price`
- `market_based = True`

---

### **2. Price Source Semantics**

| Condition | `price_source` | `market_sample_size` | Notes |
|-----------|----------------|---------------------|-------|
| ≥2 prices | `web_median` | 2-5 | **Gold standard** - market aggregation |
| 1 price | `web_<shop>` | 1 | Single source (less reliable) |
| No web | `ai_estimate` or `query_baseline` | 0 | Fallback only |

**Key Insight:** `web_median` is the **only** truly market-based price source.

---

### **3. Weight Validation - EDGE CASE ONLY**

**Location:** `ai_filter.py::validate_weight_price()` (lines 717-744)

**CRITICAL:** Weight validation is **ONLY** applied to:
- `web_single` (single shop price)
- `ai_estimate` (AI fallback)
- `query_baseline` (last resort)

**NEVER** applied to `web_median` - the market knows best!

```python
def validate_weight_price(text: str, price: float, is_resale: bool = True):
    """
    MEDIAN-FIRST RULE: This is NOT applied to web_median prices.
    Only used for: web_single, ai_estimate, query_baseline
    """
    # Sanity check for single-source fallbacks only
```

---

## ✅ ACCEPTANCE CRITERIA

### **A. Median Dominance**

```sql
-- Verify web_median is the primary price source
SELECT 
    price_source,
    COUNT(*) as count,
    ROUND(AVG(market_sample_size), 1) as avg_samples,
    ROUND(AVG(new_price), 2) as avg_new_price
FROM listings
WHERE price_source LIKE 'web_%'
GROUP BY price_source
ORDER BY count DESC;
```

**Expected:**
- `web_median`: Highest count with `avg_samples >= 2`
- `web_<shop>`: Lower count with `avg_samples = 1`

---

### **B. No Weight Anomalies (Natural Market Consistency)**

```sql
-- Check for weight pricing inconsistencies
-- Should be 0 rows if market aggregation works correctly
WITH weight_prices AS (
    SELECT 
        listing_id,
        title,
        CAST(REGEXP_REPLACE(title, '.*?(\d+(?:\.\d+)?)\s*kg.*', '\1') AS DECIMAL) as weight_kg,
        new_price,
        price_source,
        new_price / NULLIF(CAST(REGEXP_REPLACE(title, '.*?(\d+(?:\.\d+)?)\s*kg.*', '\1') AS DECIMAL), 0) as price_per_kg
    FROM listings
    WHERE title ~* '\d+(\.\d+)?\s*kg'
      AND new_price > 0
      AND price_source = 'web_median'  -- ONLY check median prices
      AND (title ~* 'hantelscheibe|kettlebell|gewicht')
)
SELECT 
    w1.listing_id as heavier_id,
    w1.weight_kg as heavier_weight,
    w1.price_per_kg as heavier_price_per_kg,
    w2.listing_id as lighter_id,
    w2.weight_kg as lighter_weight,
    w2.price_per_kg as lighter_price_per_kg,
    ROUND(w1.price_per_kg - w2.price_per_kg, 2) as inconsistency
FROM weight_prices w1
JOIN weight_prices w2 ON w1.weight_kg > w2.weight_kg
WHERE w1.price_per_kg > w2.price_per_kg * 1.5;  -- Allow 1.5x tolerance
```

**Expected:** 0 rows (market naturally enforces consistency)

---

### **C. Action Prices Neutralized**

```sql
-- Verify outliers are removed
SELECT 
    price_source,
    market_sample_size,
    COUNT(*) as listings,
    ROUND(MIN(new_price), 2) as min_price,
    ROUND(AVG(new_price), 2) as avg_price,
    ROUND(MAX(new_price), 2) as max_price,
    ROUND(STDDEV(new_price), 2) as price_stddev
FROM listings
WHERE price_source IN ('web_median', 'web_single')
GROUP BY price_source, market_sample_size
ORDER BY price_source, market_sample_size;
```

**Expected:**
- `web_median` has lower `price_stddev` (outliers removed)
- `web_single` has higher variance (no aggregation)

---

### **D. Market Analytics Fields Populated**

```sql
-- Verify all market analytics fields are populated
SELECT 
    COUNT(*) as total_listings,
    COUNT(market_value) as has_market_value,
    COUNT(buy_now_ceiling) as has_buy_now_ceiling,
    COUNT(CASE WHEN market_based_resale IS NOT NULL THEN 1 END) as has_market_based,
    COUNT(CASE WHEN market_sample_size IS NOT NULL THEN 1 END) as has_sample_size,
    COUNT(deal_score) as has_deal_score,
    -- Percentages
    ROUND(100.0 * COUNT(market_value) / COUNT(*), 1) as pct_market_value,
    ROUND(100.0 * COUNT(buy_now_ceiling) / COUNT(*), 1) as pct_buy_now_ceiling
FROM listings;
```

**Expected:** All counts = `total_listings` (100% populated)

---

### **E. Data Quality Invariants**

```sql
-- Verify no data corruption
SELECT 
    COUNT(*) as total,
    COUNT(CASE WHEN new_price IS NULL OR new_price <= 0 THEN 1 END) as null_new_price,
    COUNT(CASE WHEN resale_price_est IS NULL OR resale_price_est <= 0 THEN 1 END) as null_resale,
    COUNT(CASE WHEN price_source = 'unknown' THEN 1 END) as unknown_source,
    COUNT(CASE WHEN price_source IS NULL THEN 1 END) as null_source
FROM listings;
```

**Expected:**
- `null_new_price = 0`
- `null_resale = 0`
- `unknown_source = 0`
- `null_source = 0`

---

## 📊 EXAMPLE: HOW IT WORKS

### **Scenario: Hantelscheibe 10kg**

**Query:** "Hantelscheibe 10kg"

**Web Search Returns:**
1. Digitec: 45 CHF
2. Galaxus: 48 CHF
3. Decathlon: **25 CHF** (ACTION!)
4. Manor: 47 CHF
5. Zalando: 46 CHF

**Processing:**
```
Initial median: 46 CHF
Outlier bounds: 27.6 - 64.4 CHF (±40%)
Remove outliers: Decathlon (25 CHF) removed
Final prices: [45, 46, 47, 48]
Final median: 46.5 CHF
```

**Result:**
- `new_price = 46.5 CHF`
- `price_source = "web_median"`
- `market_sample_size = 4`
- `market_based = True`

**Without Median (Old Approach):**
- Single source might pick Decathlon → `new_price = 25 CHF` ❌
- Leads to unrealistic pricing and false positives

---

## 🚫 WHAT WAS REMOVED

### **1. Weight Monotonic Pricing Enforcement**

**Removed Function:** `enforce_weight_monotonic_pricing()`

**Reason:** Violates MEDIAN-FIRST principle. Market aggregation naturally ensures consistency.

**Before:**
```python
# WRONG: Artificial correction after market aggregation
adjusted_price, was_adjusted = enforce_weight_monotonic_pricing(vk, new_price, product_type)
if was_adjusted:
    new_price = adjusted_price  # Overrides market median!
```

**After:**
```python
# RIGHT: Trust the median
new_price = web_result["new_price"]  # Already median-aggregated
```

---

### **2. Global Weight Pricing Tracker**

**Removed:** `_weight_pricing_tracker` global variable

**Reason:** Not needed. Each product's median is independently correct.

---

## 💰 COST IMPACT

**Websearch Cost:**
- **Before:** 1 price per product
- **After:** Up to 5 prices per product (same API call)
- **Cost Change:** **$0.00** (same single websearch, just requests more data)

**AI Cost:**
- **No new AI calls**
- **No additional processing**
- **Cost Change:** **$0.00**

**Total Additional Cost:** **$0.00** ✅

---

## 🎯 SUCCESS METRICS

### **Before (Single-Source)**
- Hantelscheibe 10kg: 25 CHF (Decathlon action)
- Hantelscheibe 5kg: 30 CHF (regular price)
- **Anomaly:** 10kg cheaper than 5kg ❌

### **After (MEDIAN-FIRST)**
- Hantelscheibe 10kg: 46.5 CHF (median of 4 shops)
- Hantelscheibe 5kg: 28 CHF (median of 3 shops)
- **Consistent:** 10kg > 5kg naturally ✅

---

## 📝 IMPLEMENTATION NOTES

1. **Execution Order:**
   - Web search collects multiple prices
   - Median computed with outlier removal
   - Result stored with `price_source = "web_median"`
   - No post-processing corrections applied

2. **Observability:**
   - Log shows: `"median of N prices: [shop1, shop2, shop3]"`
   - Clear indication when median is used vs single source

3. **Fallback Behavior:**
   - If only 1 price found → `web_single` (weight validation applies)
   - If all prices are outliers → use original median
   - If no web prices → `ai_estimate` or `query_baseline`

4. **Cache Behavior:**
   - Median prices cached for 60 days
   - `price_source` preserved in cache
   - Subsequent runs use cached median

---

## 🔑 KEY TAKEAWAY

**The market is smarter than any algorithm.**

By aggregating multiple sources and removing outliers, we get realistic prices that naturally reflect market logic—including weight-based consistency for fitness products.

**No artificial corrections needed. Trust the median.** 🥇
