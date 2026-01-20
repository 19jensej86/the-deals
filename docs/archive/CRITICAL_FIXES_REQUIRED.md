# 🔴 CRITICAL FIXES - $3 USD COST EXPLOSION

**Status:** SYSTEM BROKEN - DO NOT RUN UNTIL FIXED
**Analysis Date:** 2026-01-19
**Last Run Cost:** $1.79 USD (4.3x over budget)

---

## 📊 ROOT CAUSE SUMMARY

### **1. ACCESSORIES NICHT GEFILTERT**

- **Problem:** `process_batch()` filtert Accessories, aber `main.py` verarbeitet sie trotzdem
- **Evidence:** 8 Garmin armbands marked `is_accessory_only=True` but saved to DB
- **Cost Impact:** $0.008 wasted on extraction + $0.08 on evaluation = **$0.09**

### **2. REKURSIVE RETRY-EXPLOSION**

- **Problem:** Websearch retry logic splits batches rekursiv ohne Budget-Check
- **Evidence:** 1 batch → 5 websearch calls (line 671, 708, 744, 774, 817)
- **Cost Impact:** $0.35 × 5 = **$1.75** (expected: $0.35)
- **Multiplier:** **5x COST EXPLOSION**

### **3. NULL PRICES IN DATABASE**

- **Problem:** Prices calculated in `ai_filter.py` but not persisted to DB
- **Evidence:** CSV shows `new_price=NULL` but log shows "New: 280.00 CHF"
- **Data Integrity:** **BROKEN**

### **4. TESTING MODE INKONSISTENT**

- **Problem:** `clear_on_start=true` clears only `listings`, not `price_history`
- **Evidence:** Line 48-49 clears listings, but no mention of other tables
- **Result:** Stale data in test runs

### **5. BUDGET GUARDS NICHT ENFORCED**

- **Problem:** Budget check exists but NEVER called in retry loop
- **Evidence:** `ai_filter.py:770-784` - no budget check before recursive call
- **Result:** Costs explode without limit

---

## 🔧 IMMEDIATE HOTFIXES (20 MINUTEN)

### **FIX #1: Filter Accessories in main.py** ⏱️ 5 min

**Location:** `main.py:406-442`

**Problem:**

```python
for query, listings in all_listings_by_query.items():
    for listing in listings:
        extracted = listing_id_to_extracted.get(listing_id)

        if extracted and extracted.products:
            # ❌ KEIN CHECK auf is_accessory_only!
            listing["variant_key"] = identity.product_key
```

**Fix:**

```python
for query, listings in all_listings_by_query.items():
    for listing in listings:
        extracted = listing_id_to_extracted.get(listing_id)

        # ✅ SKIP ACCESSORIES
        if extracted and extracted.is_accessory_only:
            continue  # Don't process accessories

        if extracted and extracted.products:
            listing["variant_key"] = identity.product_key
```

**Impact:** Saves $0.09 per run, prevents 8 accessories from being evaluated

---

### **FIX #2: Remove Recursive Retry** ⏱️ 10 min

**Location:** `ai_filter.py:763-785`

**Problem:**

```python
except json.JSONDecodeError as e:
    if len(batch) > 5:
        # ❌ REKURSIVE RETRY OHNE LIMIT!
        mid = len(batch) // 2
        for sub_batch in [batch[:mid], batch[mid:]]:
            sub_results = search_web_batch_for_new_prices(
                sub_batch, category=category, query_analysis=query_analysis
            )
```

**Fix:**

```python
except json.JSONDecodeError as e:
    print(f"⚠️ Batch web search failed: {e}")

    # ✅ KEIN RETRY IN TEST MODE
    from runtime_mode import get_mode_config
    mode_config = get_mode_config(cfg.runtime.mode)

    if not mode_config.retry_enabled:
        print("🚫 Retry disabled in test mode - using fallback")
        continue

    # ✅ MAX 1 RETRY
    if len(batch) > 5 and retry_count < 1:
        print(f"🔄 Retrying ONCE with smaller batch...")
        mid = len(batch) // 2
        # ... retry logic
    else:
        print("🚫 Max retries reached - using fallback")
        continue
```

**Impact:** Prevents 5x cost explosion, saves $1.40 per run

---

### **FIX #3: Add Budget Check in Retry** ⏱️ 3 min

**Location:** `ai_filter.py:770` (before retry)

**Add:**

```python
# ✅ BUDGET CHECK BEFORE RETRY
from runtime_mode import is_budget_exceeded, get_mode_config
mode_config = get_mode_config(cfg.runtime.mode)

if is_budget_exceeded(mode_config, get_run_cost_summary()["total_usd"]):
    print("🚫 Budget exceeded - stopping websearch")
    return {}
```

**Impact:** Hard stop on cost explosion

---

### **FIX #4: Truncate ALL Tables in Test Mode** ⏱️ 2 min

**Location:** `main.py:1348` (or wherever DB clear happens)

**Problem:**

```python
if cfg.runtime.mode == "testing" and cfg.db.clear_on_start:
    cur.execute("DELETE FROM listings")  # ❌ NUR LISTINGS!
```

**Fix:**

```python
from runtime_mode import get_mode_config, should_truncate_db

mode_config = get_mode_config(cfg.runtime.mode)

if should_truncate_db(mode_config):
    for table in mode_config.truncate_tables:
        cur.execute(f"DELETE FROM {table}")
        print(f"🧹 Cleared {table}")
```

**Impact:** Clean test state, no stale data

---

## 🟡 SHORT-TERM FIXES (1-2 STUNDEN)

### **FIX #5: Fix Price Persistence**

**Problem:** Prices calculated but not saved to DB

**Solution:** Create unified data structure that carries prices from `ai_filter.py` to `main.py`

**Files to modify:**

- `ai_filter.py` - return prices in structured format
- `main.py` - save prices from structured format

---

### **FIX #6: Integrate runtime_mode.py**

**Steps:**

1. Import `runtime_mode` in `main.py`
2. Replace all `cfg.runtime.mode` checks with `mode_config`
3. Replace all `cfg.websearch.enabled` with `should_use_websearch()`
4. Replace all budget checks with `is_budget_exceeded()`

**Impact:** Single source of truth, no more flag confusion

---

### **FIX #7: Reduce Batch Size**

**Location:** `ai_filter.py:612`

**Change:**

```python
# OLD:
batch_size = int(max_products_per_batch * 0.8)  # ~32 products

# NEW:
batch_size = 10  # Smaller batches = less JSON truncation
```

**Impact:** Fewer websearch failures

---

## 📈 EXPECTED RESULTS AFTER FIXES

### **BEFORE (Current):**

```
Test Run Cost:        $1.79
Accessories Filtered: 0/8 (0%)
Websearch Calls:      5
Data Integrity:       BROKEN
```

### **AFTER (With Fixes):**

```
Test Run Cost:        $0.15 - $0.20  ✅ (90% reduction)
Accessories Filtered: 8/8 (100%)     ✅
Websearch Calls:      1              ✅
Data Integrity:       GOOD           ✅
```

---

## ⚠️ RECOMMENDATION

**❌ DO NOT RUN AGAIN UNTIL:**

1. Fix #1 applied (accessories)
2. Fix #2 applied (retry)
3. Fix #3 applied (budget)
4. Fix #4 applied (truncate)

**Minimum time:** 20 minutes
**Expected savings:** $1.60 per run (90% cost reduction)

**AFTER FIXES:**
✅ Test with 1 query first
✅ Verify cost < $0.20
✅ Check DB for NULL prices
✅ Confirm accessories filtered

---

## 🔍 VERIFICATION CHECKLIST

After applying fixes, verify:

- [ ] `runtime_mode.py` exists and works
- [ ] Accessories are skipped in `main.py:406`
- [ ] Retry logic has max_retries=1
- [ ] Budget check before each websearch
- [ ] All tables truncated in test mode
- [ ] Test run costs < $0.20
- [ ] No NULL prices in DB
- [ ] No accessories in output

---

**Last Updated:** 2026-01-19 08:57 UTC+01:00
**Priority:** 🔴 CRITICAL - BLOCKING
