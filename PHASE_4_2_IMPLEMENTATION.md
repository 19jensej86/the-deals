# Phase 4.2: Architectural Alignment - Implementation Summary

## Objective
Introduce ONE canonical identity as single source of truth for product creation, market prices, and soft market aggregation.

## Changes Implemented

### 1. ✅ CANONICAL IDENTITY KEY DEFINED

**File:** `models/product_identity.py`

**Added brand inference (lines 234-261):**
```python
@staticmethod
def infer_brand(model_or_type: str) -> str:
    """Deterministic brand inference from model name."""
    BRAND_RULES = {
        "apple": ["iphone", "ipad", "airpods", "macbook", "apple watch", "imac"],
        "samsung": ["galaxy"],
        "google": ["pixel"],
        "sony": ["playstation", "wh-1000"],
        "garmin": ["fenix", "forerunner", "vivoactive"],
        "bose": ["quietcomfort", "soundlink"],
    }
    # Returns inferred brand or None
```

**Enhanced canonical_identity_key (lines 263-343):**
- Format: `brand_model_tier_generation` (underscore-separated)
- Includes: brand (inferred if missing), model, tier (mini/pro/max), generation
- Excludes: storage, color, condition, marketing terms
- Normalizes: generations to `gen_X` format

**Examples:**
```
"Apple iPhone 12 mini 128GB" → "apple_iphone_12_mini"
"iPhone 12 Pro Max"          → "apple_iphone_12_pro_max"
"AirPods Pro (2nd Generation)" → "apple_airpods_pro_gen_2"
```

### 2. ✅ PRODUCT CREATION ALIGNED

**File:** `db_pg_v2.py`

**Updated `get_or_create_product()` (lines 265-315):**
- Now searches by `base_product_key` FIRST (canonical identity)
- Ensures: 1 canonical_identity_key = exactly 1 product
- Fallback to variant_key for backwards compatibility

**Updated `save_evaluation()` (lines 1400-1418):**
- Uses `_identity_key` as `base_product_key` for product creation
- Fallback to heuristic if `_identity_key` not available

**Impact:**
- "Apple AirPods Pro 2nd Gen" and "AirPods Pro (2. Generation)" → same product
- No more duplicate products for same canonical identity

### 3. ✅ MARKET PRICE AGGREGATION FIXED

**File:** `ai_filter.py`

**Updated `calculate_all_market_resale_prices()` (lines 2220-2248):**
- Groups by `_identity_key` instead of `variant_key`
- Allows cross-variant aggregation (128GB + 256GB together)
- Logs variant count per identity

**Updated `calculate_market_resale_from_listings()` (lines 1982-2223):**
- Filters by `_identity_key` instead of `variant_key`
- Aggregates listings across storage/color variants

**Impact:**
- iPhone 12 mini 128GB + iPhone 12 mini 256GB → aggregate market data
- Market prices > 0 when bids exist across variants

### 4. ⚠️ SOFT MARKET - PARTIAL (2-pass needed)

**Current Status:**
- Soft market still uses same-run aggregation (Fix #4 from emergency session)
- 2-pass evaluation NOT YET implemented
- Will be addressed in next iteration

**Why 2-pass is needed:**
- Current: Iteration order prevents listings from seeing each other
- Solution: Pass 1 = collect all by identity, Pass 2 = evaluate with grouped data

### 5. ❌ TESTS - NOT YET ADDED

**Planned tests:**
- iPhone 12 vs 12 mini vs 12 Pro are NOT merged
- Multiple AirPods Pro (2nd gen) titles → 1 product
- Market price aggregation > 0 when bids exist

**Will be added in final step.**

---

## Data Flow: Listing → Identity → Product → Pricing

### Example: iPhone 12 mini listings

**Input listings:**
```
1. "IPhone 12 Mini 128Gb Weiss"
2. "iPhone 12 mini"
3. "iPhone 12 mini, 128GB, Grün"
4. "Iphone 12 Mini 128gb"
5. "iPhone 12 mini A2399 128GB"
6. "Apple iPhone 12 mini 128 GB, Weiss"
```

**Step 1: Extraction → canonical_identity_key**
```
Listing 1 → identity: "apple_iphone_12_mini"
Listing 2 → identity: "apple_iphone_12_mini"
Listing 3 → identity: "apple_iphone_12_mini"
Listing 4 → identity: "apple_iphone_12_mini"
Listing 5 → identity: "apple_iphone_12_mini_a2399"  (model variant)
Listing 6 → identity: "apple_iphone_12_mini"
```

**Step 2: Product Creation**
```
base_product_key = "apple_iphone_12_mini"
→ Check if product exists with this base_product_key
→ If yes: reuse product_id
→ If no: create new product

Result: 2 products created
- Product 1: base_product_key="apple_iphone_12_mini" (5 listings)
- Product 2: base_product_key="apple_iphone_12_mini_a2399" (1 listing)
```

**Step 3: Market Price Aggregation**
```
identity_key = "apple_iphone_12_mini"
→ Find all listings with _identity_key = "apple_iphone_12_mini"
→ Aggregate bids across all variants (128GB, 256GB, colors)
→ Calculate market_resale_price

Result: market_prices["apple_iphone_12_mini"] = {
  "resale_price": 87.40,
  "source": "auction_demand_moderate",
  "sample_size": 5,
  "variants": 5
}
```

**Step 4: Soft Market (when implemented)**
```
identity_key = "apple_iphone_12_mini"
→ Pass 1: Group all listings by identity_key
→ Pass 2: Apply soft market cap using grouped data
→ Result: Conservative ceiling based on live bids
```

---

## Expected Impact

### Before (Broken):
```
8 iPhone 12 listings:
- 8 different identities (fragmentation)
- 0 market prices (no aggregation)
- 100% soft market skip (no data)
- 2 duplicate products created
```

### After (Fixed):
```
8 iPhone 12 listings:
- 2 unique identities (apple_iphone_12_mini, apple_iphone_12_mini_a2399)
- 1-2 market prices (aggregation works)
- Soft market: TBD (needs 2-pass)
- 2 products (no duplicates)
```

---

## Remaining Work

### Critical:
1. **Implement 2-pass soft market evaluation**
   - Pass 1: Collect all listings grouped by canonical_identity_key
   - Pass 2: Evaluate with grouped data available
   - Location: `main.py` evaluation loop

### Important:
2. **Add deterministic tests**
   - Test identity generation edge cases
   - Test product deduplication
   - Test market price aggregation

### Nice-to-have:
3. **Update soft market to use canonical identity**
   - Currently uses `search_identity`
   - Should use `_identity_key` for consistency

---

## Files Modified

1. `models/product_identity.py` - Brand inference + canonical identity
2. `db_pg_v2.py` - Product creation alignment
3. `ai_filter.py` - Market price aggregation by identity
4. `main.py` - Already stores `_identity_key` (from emergency fix)

---

## Verification Commands

After next run, check:

```sql
-- Should show fewer products (no duplicates)
SELECT base_product_key, COUNT(*) as product_count
FROM products
GROUP BY base_product_key
HAVING COUNT(*) > 1;

-- Should show market prices > 0
SELECT COUNT(*) FROM deals WHERE market_based = true;

-- Should show canonical identities
SELECT DISTINCT base_product_key FROM products
WHERE base_product_key LIKE '%iphone_12%';
```

Expected results:
- 0 duplicate base_product_keys
- Market prices > 0 (if bids exist)
- Canonical format: `apple_iphone_12_mini` (not `Apple iPhone 12 Mini`)
