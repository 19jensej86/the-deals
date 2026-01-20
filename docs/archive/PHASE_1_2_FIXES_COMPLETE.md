# PHASE 1 & 2 — COMPLETE FIX SUMMARY

**Date:** 2026-01-13  
**Status:** ✅ ALL FIXES IMPLEMENTED

---

## 📊 PHASE 1 — ROOT CAUSE ANALYSIS (PROVEN)

### CRITICAL FINDING: Budget Key Name Mismatch

**Problem:** Web search blocked with `3.20 USD >= 3.0 USD` despite config.yaml setting `daily_cost_usd_max: 5.00`

**Root Cause:** `apply_ai_budget_from_cfg()` looks for WRONG key names

| Component | Key Name | File:Line |
|-----------|----------|-----------|
| **config.yaml** | `daily_cost_usd_max` | `configs/config.yaml:117` |
| **ai_filter.py expects** | `daily_cost_limit` | `ai_filter.py:2856` (OLD) |
| **Result** | ❌ MISMATCH → Falls back to hardcoded 3.00 USD |

### Evidence Chain

1. **Config loads correctly:** `config.py:226` → `budget=ai.get("budget", {})` ✅
2. **Budget application fails:** `ai_filter.py:2856` → `get_val("daily_cost_limit", None)` returns `None` ❌
3. **Falls back to default:** `ai_filter.py:136` → `DAILY_COST_LIMIT = 3.00` ❌
4. **Runtime check uses wrong value:** `last_run.log:305` → `3.20 USD >= 3.0 USD` ❌

---

## 🔧 PHASE 2 — FIXES IMPLEMENTED

### ✅ FIX 1: Budget Key Name Mismatch

**File:** `ai_filter.py:2842-2868`

**Change:** Corrected key names to match config.yaml structure

**Before:**
```python
val = get_val("daily_cost_limit", None)  # ❌ Wrong key
if val is not None:
    DAILY_COST_LIMIT = val
```

**After:**
```python
budget = get_val("budget", {})
if budget:
    val = budget.get("daily_cost_usd_max")  # ✅ Correct key
    if val is not None:
        DAILY_COST_LIMIT = val
        print(f"   💰 Budget limit loaded: {val} USD (from config.yaml)")
```

**Impact:**
- Budget limit now correctly reads 5.00 USD from config.yaml
- Web search limit now correctly reads 100 from config.yaml
- Logs show exact values loaded at startup

---

### ✅ FIX 2: Web Search Execution Proof

**File:** `ai_filter.py:722-723`

**Change:** Added explicit logging when web search is ACTUALLY executed

**Added:**
```python
# FIX 2: Proof of web search execution
print(f"   🌐 WEB SEARCH EXECUTED for {len(batch)} products (Claude Sonnet + web_search tool)")
```

**Also changed:**
```python
print(f"   ✅ WEB PRICE: {vk[:40]}... = {price} CHF ({shop})")
```

**Impact:**
- Logs now clearly show when REAL web search happens (not AI fallback)
- Distinguishes between cached prices and fresh web searches
- Proves web search tool was actually invoked

---

### ✅ FIX 3: web_search_used Accuracy

**File:** `main.py:94-132`

**Status:** Already correctly implemented

**Function:** `_check_web_search_used(variant_info, ai_result)`
- Checks parent `price_source` for "web" prefix ✅
- Checks ALL bundle components for "web" price sources ✅
- Returns `True` if ANY component used web search ✅

**No changes needed** - logic is correct.

---

### ✅ FIX 4: Bundle Escalation Logic

**File:** `pipeline/decision_gates.py:48-51, 107-110`

**Change 1:** Force detail scraping for bundles with empty components

**Added to `decide_next_step()`:**
```python
# FIX 4: Bundles with empty components MUST have detail scraping
if extracted.bundle_type != BundleType.SINGLE_PRODUCT:
    if not extracted.products or len(extracted.products) == 0:
        return "detail"  # Force detail scraping to extract components
```

**Change 2:** Explicit skip reason for unresolved bundles

**Added to `should_skip()`:**
```python
# FIX 4: Bundles with empty components after detail scraping = explicit skip
if extracted.bundle_type != BundleType.SINGLE_PRODUCT:
    if not extracted.products or len(extracted.products) == 0:
        return (True, "bundle_components_empty_after_detail_scraping")
```

**Impact:**
- Bundles like "6 Stk" will trigger detail scraping to extract components
- If detail scraping fails to extract components, explicit skip reason is logged
- No more zero-price bundles without explanation

---

## 📋 FILES MODIFIED

1. **`ai_filter.py`**
   - Lines 2842-2868: Fixed budget key names
   - Lines 722-723: Added web search execution proof logging
   - Line 754: Enhanced web price logging

2. **`pipeline/decision_gates.py`**
   - Lines 48-51: Force detail scraping for empty bundle components
   - Lines 107-110: Explicit skip reason for unresolved bundles

3. **`main.py`**
   - Lines 94-132: `_check_web_search_used()` (already correct, no changes)

---

## ✅ ACCEPTANCE CRITERIA

### 1. Budget Limit Correctly Applied

**Run:** `python main.py`

**Expected in logs:**
```
   💰 Budget limit loaded: 5.0 USD (from config.yaml)
   🌐 Web search limit loaded: 100 searches (from config.yaml)
```

**NOT:**
```
   🚫 Daily budget exceeded (3.20 USD >= 3.0 USD)
```

**Verify:**
- [ ] Budget limit shows 5.0 USD (not 3.0)
- [ ] Web search executes (not blocked by budget)

---

### 2. Web Search Execution Proof

**Expected in logs:**
```
🌐 v7.3.4: SINGLE web search for 21 products (cost-optimized)
   ⏳ Waiting 120s upfront (proactive rate limit prevention)...
   🌐 WEB SEARCH EXECUTED for 21 products (Claude Sonnet + web_search tool)
   ✅ WEB PRICE: Garmin Forerunner 970... = 199.00 CHF (Galaxus)
```

**Verify:**
- [ ] "WEB SEARCH EXECUTED" appears in logs
- [ ] At least 1 "WEB PRICE" result shown
- [ ] NOT all "AI fallback"

---

### 3. web_search_used Accuracy

**SQL Check:**
```sql
SELECT listing_id, title, price_source, web_search_used, is_bundle
FROM listings
WHERE web_search_used = 1;
```

**Expected:**
- At least 1 listing with `web_search_used = 1`
- For bundles: `web_search_used = 1` if ANY component used web price

**Verify:**
- [ ] `web_search_used = 1` for listings with `price_source` starting with "web_"
- [ ] `web_search_used = 1` for bundles with web-priced components

---

### 4. Bundle Escalation

**Expected in logs for "6 Stk" bundles:**
```
[X/24] Hantelscheiben Set, Guss, 6 Stk...
   🔍 Detail scraping: https://...
   ✅ Extracted: components=6
```

**OR if detail scraping fails:**
```
⏭️ Saved: Hantelscheiben Set, Guss, 6 Stk...
   Skip reason: bundle_components_empty_after_detail_scraping
```

**SQL Check:**
```sql
SELECT listing_id, title, is_bundle, bundle_components, skip_reason
FROM listings
WHERE is_bundle = 1;
```

**Verify:**
- [ ] Bundles have `bundle_components` populated OR
- [ ] Bundles have explicit `skip_reason` if components empty

---

## 🚀 NEXT STEPS

1. **Run the pipeline:**
   ```powershell
   python main.py
   ```

2. **Check logs for:**
   - Budget limit loaded: 5.0 USD ✅
   - WEB SEARCH EXECUTED ✅
   - WEB PRICE results ✅
   - Bundle detail scraping triggered ✅

3. **Verify database:**
   ```sql
   SELECT COUNT(*) FROM listings WHERE web_search_used = 1;
   SELECT COUNT(*) FROM listings WHERE is_bundle = 1 AND bundle_components != '[]';
   ```

4. **Expected outcomes:**
   - At least 1 web search executed
   - At least 1 listing with `web_search_used = 1`
   - Bundles either have components OR explicit skip reason

---

## 💡 KEY INSIGHTS

1. **Config key mismatch was the blocker** - not budget/limit values themselves
2. **Logging was insufficient** - couldn't diagnose without explicit execution proof
3. **Bundle escalation existed** - but needed explicit empty-component check
4. **web_search_used logic was correct** - just never triggered due to budget block

**All fixes are minimal, surgical, and targeted** - no architecture changes, no refactors, just fixing the broken connections.
