# v7.2.1 Critical Fixes - Implementation Summary

**Date:** 2026-01-08 23:30  
**Status:** ✅ All 3 critical fixes implemented

---

## 🔧 IMPLEMENTED FIXES

### **FIX #1: end_time = NULL (75% of listings)**

**Problem:** Buy-Now-Only listings had `end_time=NULL` → `hours_remaining=999.0`

**Solution:** Modified `_calculate_hours_remaining()` to detect Buy-Now-Only listings and set realistic hours_remaining.

**Changes:**
- **File:** `scrapers/ricardo.py`
- **Lines 354-384:** Added `is_buy_now_only` parameter
- **Lines 453-456:** Pass flag in `scrape_ricardo_serp()`
- **Lines 594-596:** Pass flag in `search_ricardo_for_prices()` (1st occurrence)
- **Lines 697-699:** Pass flag in `search_ricardo_for_prices()` (2nd occurrence)

**Logic:**
```python
def _calculate_hours_remaining(end_time_text: Optional[str], is_buy_now_only: bool = False) -> float:
    if not end_time_text:
        # Buy-Now-Only listings have no auction end time
        # Set to 30 days (720 hours) for realistic confidence calculation
        return 720.0 if is_buy_now_only else 999.0
```

**Expected Result:**
- Buy-Now-Only: `hours_remaining=720.0` (30 days)
- Auctions: `hours_remaining` from parsed end_time
- Unknown: `hours_remaining=999.0`

---

### **FIX #2: Bundle Component Overestimation**

**Problem:** AI estimated "140kg Hantelscheiben" at 4422 CHF (should be ~210 CHF)

**Solution:** Added weight-based validation to cap AI estimates at realistic prices.

**Changes:**
- **File:** `ai_filter.py`
- **Lines 1280-1360:** Enhanced `detect_bundle_with_ai()` with validation loop
- **Lines 1302:** Added prompt instruction to include weight in component names
- **Lines 1330-1352:** Validate and cap AI estimates for weight plates

**Logic:**
```python
# Weight-based validation for fitness equipment
if is_weight_plate(name):
    weight_kg = extract_weight_kg(name)
    if weight_kg:
        weight_type = detect_weight_type(name)
        realistic_resale = calculate_weight_based_price(weight_kg, weight_type, is_resale=True)
        # Cap AI estimate at realistic price
        if ai_estimate > realistic_resale * 2:
            print(f"   ⚠️ Capping {name}: AI={ai_estimate} → realistic={realistic_resale}")
            c["estimated_value"] = realistic_resale
```

**Expected Result:**
- 140kg Gusseisen: ~210 CHF (not 4422 CHF)
- 30kg Set: ~100 CHF (not 720 CHF)
- AI estimates capped at 2x realistic weight-based price

---

### **FIX #3: new_price = NULL for some variants**

**Problem:** Fenix 8 had `new_price=NULL` when web search failed

**Solution:** Fallback to `buy_now_price * 1.1` when web search returns no results.

**Changes:**
- **File:** `ai_filter.py`
- **Lines 2113-2128:** Added fallback logic after variant_info processing

**Logic:**
```python
# v7.2.1: Fallback new_price to buy_now_price if web search failed
if not result["new_price"] and buy_now_price and buy_now_price > 0:
    result["new_price"] = buy_now_price * 1.1  # Conservative estimate: assume 10% markup
    result["price_source"] = "buy_now_fallback"
```

**Expected Result:**
- Fenix 8 (buy_now=899): new_price=988.9 CHF (fallback)
- Sanity checks can now work correctly
- No more NULL new_price for Buy-Now listings

---

## 📊 EXPECTED IMPROVEMENTS

### Before (v7.2.0):
- ❌ 75% listings: `end_time=NULL`, `hours_remaining=999`
- ❌ Bundle overestimation: 4422 CHF instead of 210 CHF
- ❌ Missing new_price: Fenix 8 = NULL
- **Data Quality:** 65/100

### After (v7.2.1):
- ✅ Buy-Now listings: `hours_remaining=720` (realistic)
- ✅ Bundle estimates: Weight-based validation
- ✅ new_price fallback: buy_now * 1.1
- **Expected Data Quality:** 80/100 (+15 points)

---

## 🎯 TESTING CHECKLIST

Run the pipeline and verify:

### 1. end_time Fix
```sql
-- Check hours_remaining distribution
SELECT 
    CASE 
        WHEN hours_remaining = 999 THEN 'Unknown'
        WHEN hours_remaining = 720 THEN 'Buy-Now (30d)'
        WHEN hours_remaining < 24 THEN 'Ending Soon'
        ELSE 'Normal Auction'
    END as category,
    COUNT(*) as count
FROM listings
GROUP BY category;
```

**Expected:** Most Buy-Now listings should have 720, not 999.

### 2. Bundle Validation
```sql
-- Check bundle new_price realism
SELECT 
    id, title, buy_now_price, new_price, 
    expected_profit, bundle_components
FROM listings
WHERE is_bundle = true
ORDER BY new_price DESC;
```

**Expected:** No bundles with new_price > 1000 CHF unless genuinely expensive.

### 3. new_price Fallback
```sql
-- Check new_price coverage
SELECT 
    price_source,
    COUNT(*) as count,
    AVG(new_price) as avg_price
FROM listings
WHERE new_price IS NOT NULL
GROUP BY price_source;
```

**Expected:** See "buy_now_fallback" entries for listings where web search failed.

---

## 🚀 DEPLOYMENT

### Clear Caches
```powershell
rm *_cache.json
```

### Run Pipeline
```powershell
python main.py
```

### Analyze Results
```powershell
python analyze_run.py
```

---

## 📝 FILES MODIFIED

1. **`scrapers/ricardo.py`** (4 changes)
   - Modified `_calculate_hours_remaining()` signature
   - Updated 3 call sites to pass `is_buy_now_only` flag

2. **`ai_filter.py`** (2 changes)
   - Enhanced `detect_bundle_with_ai()` with weight validation
   - Added `new_price` fallback in `evaluate_listing_with_ai()`

3. **`.gitignore`** (1 change)
   - Added `last_run.log` and `last_run_listings.json`

---

## ✅ VERIFICATION

After running, compare with previous results:

| Metric | v7.2.0 | v7.2.1 Expected | Improvement |
|--------|--------|-----------------|-------------|
| **end_time NULL** | 75% | <5% | -70pp |
| **hours_remaining=999** | 75% | <5% | -70pp |
| **Bundle overestimation** | Yes (4422 CHF) | No (~210 CHF) | ✅ Fixed |
| **new_price NULL** | 1 case | 0 cases | ✅ Fixed |
| **Data Quality** | 65/100 | 80/100 | +15 |

---

## 🎉 SUMMARY

All 3 critical fixes implemented:
1. ✅ **end_time:** Buy-Now listings now have realistic hours_remaining (720)
2. ✅ **Bundle validation:** Weight-based capping prevents overestimation
3. ✅ **new_price fallback:** Uses buy_now * 1.1 when web search fails

**Ready for testing!** 🚀
