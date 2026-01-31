# CODEBASE CLEANUP SUMMARY

**Date:** 2026-01-31  
**Context:** Database reset complete. Decisive cleanup before production testing.

---

## FILES DELETED

### **Documentation (41 files deleted)**

**Obsolete .md files removed:**

- AFTER_RUN_ANALYSIS_GUIDE.md
- ARCHITECTURE_v9_PIPELINE.md
- CLEANUP_ANALYSIS.md
- CODEBASE_AUDIT_2026-01-20.md
- DB_SCHEMA_V11.md
- FIXES_APPLIED_SUMMARY.md
- HAIKU_4.5_MIGRATION.md
- HARDENING_COMPLETE.md
- MIGRATION_HARDENING_REPORT.md
- OPTIMIZATION_SUMMARY_2026-01-20.md
- REVISED_LIVE_MARKET_LOGIC.md
- SCHEMA_V2.2_RATIONALE.md
- TEST_RUN_READY.md
- TYPE_SAFETY_FIX_COMPLETE.md
- WINDSURF_WORKFLOW.md
- docs/archive/\* (30+ archived analysis files)

**Kept (3 files):**

- ✅ README.md (main documentation)
- ✅ PRICING_ANALYSIS.md (Phase 4.1c findings)
- ✅ PHASE_4_1C_IMPLEMENTATION_SUMMARY.md (current state)

---

### **SQL Files (8 files deleted)**

**Obsolete schemas and migrations removed:**

- analyze_results.sql (ad-hoc query)
- db_schema_optimized.sql (obsolete)
- schema_v2.sql (old version)
- schema_v2.1_FINAL.sql (old version)
- schema_v2.2.1_PATCH.sql (applied)
- schema_v2.2.2_PATCH.sql (applied)
- validate_data.sql (ad-hoc query)
- migrations/phase_4_1c_pricing_truth.sql (obsolete - no ended auction access)

**Kept (1 file):**

- ✅ schema_v2.2_FINAL.sql (current schema)

---

### **Python Files (3 files deleted)**

**Obsolete helpers removed:**

- db_pg.py (old database version, replaced by db_pg_v2.py)
- ai_filter_commodity_helper.py (temporary helper, function moved to ai_filter.py)
- db_query_helper.py (temporary analysis helper)

---

## DEAD CODE IDENTIFIED

### **1. Historical Price Collection (OBSOLETE)**

**Location:** `db_pg_v2.py` lines 819-860

**Dead functions:**

```python
def record_price_if_changed(conn, listing_id, new_price, bids_count)
def get_price_history(conn, listing_id)
```

**Why obsolete:**

- Cannot access ended auctions on Ricardo
- `price_history` table will remain empty
- No historical learning possible

**Still imported in main.py (line 55) but never called**

**Action needed:** Remove these functions and their import

---

### **2. Learned Resale Estimate Logic (OBSOLETE)**

**Location:** `db_pg_v2.py` lines 366-400, `main.py` lines 605-641

**Dead functions:**

```python
def get_product_resale_estimate(conn, product_id)
def get_product_resale_batch(conn, product_ids)
```

**Dead code in main.py:**

```python
# Lines 605-641: Fetch learned resale estimates
learned_resale_map = get_product_resale_batch(conn, product_ids_to_fetch)
# Inject into variant_info...
```

**Why obsolete:**

- `products.resale_estimate` will remain NULL (no observations)
- Live-market-first is the only truth source
- No historical data to populate from

**Action needed:** Remove this entire code path

---

### **3. Bundle/Set Logic (OUT OF SCOPE)**

**Location:** Multiple files

**Dead/disabled code:**

- `extraction/bundle_classifier.py` (entire file)
- `models/bundle_types.py` (entire file)
- `ai_filter.py` - bundle detection and pricing functions
- `db_pg_v2.py` - bundle save/export functions

**Why obsolete:**

- Bundles explicitly out of scope
- Don't work correctly yet
- Focus only on single-product listings

**Action needed:**

- Keep files (may be needed later)
- Ensure bundle logic is disabled in pipeline
- Add clear "BUNDLES DISABLED" markers

---

### **4. Outdated Comments and Assumptions**

**Location:** Throughout codebase

**Examples found:**

- `ai_filter.py` line 13: "price_history is the single source of truth" (FALSE - no access to ended auctions)
- `main.py` line 625: "Loaded learned resale estimates" (will always be 0)
- Various "v7.x" version comments (outdated)

**Action needed:** Update comments to reflect live-market-first reality

---

## PRICING LOGIC VERIFICATION

### **✅ CORRECT: Bid-Count Weighting**

**Location:** `ai_filter.py` lines 1647-1667

```python
if bids >= 5:
    bid_weight = 1.00  # Strong signal
elif bids >= 3:
    bid_weight = 0.80  # Good signal
elif bids == 2:
    bid_weight = 0.60  # Moderate signal
elif bids == 1:
    bid_weight = 0.35  # WEAK signal (never dominant)
```

✅ **Verified:** 1-bid listings have 0.35 weight, never dominant

---

### **✅ CORRECT: Start-Price Filtering**

**Location:** `ai_filter.py` lines 1816-1826

```python
if bids == 1:
    # HARD EXCLUSION: price_ratio < 0.45
    if price_ratio < 0.45:
        continue

    # HARD EXCLUSION: Clear start-price effect
    if current <= 1.0:
        continue
```

✅ **Verified:** Start prices (≤1 CHF) and low bids (<45%) are excluded

---

### **✅ CORRECT: High-Bid Early Auction Acceptance**

**Location:** `ai_filter.py` lines 1732-1735

```python
# High activity overrides time concerns
if bids_count >= 5:
    if current_price >= minimum_for_market:  # 20% of reference
        return True, "market_high_activity"
```

✅ **Verified:** Early auctions with ≥5 bids accepted IF price is realistic (≥20% reference)

---

### **⚠️ ISSUE: Low-Price High-Bid Auctions**

**Location:** `ai_filter.py` lines 1711-1712

```python
if price_ratio < 0.20:
    return False, f"unrealistic_price_{price_ratio*100:.0f}pct"
```

✅ **Verified:** Auctions <20% of reference are rejected, even with many bids

- This correctly filters start-price artifacts

---

### **✅ CORRECT: Confidence Scoring**

**Location:** `ai_filter.py` lines 1958-1976

```python
# Base confidence
confidence = 0.50 + (sample_factor * 0.25) + (bid_factor * 0.15)

# CRITICAL: Cap confidence contribution from 1-bid listings
if weak_signal_count > 0:
    if weak_signal_count >= len(price_samples) / 2:
        confidence = min(confidence, 0.60)  # Cap if weak signals dominate
```

✅ **Verified:** Confidence matches signal quality

- Single high-quality (≥3 bids): 0.50-0.65
- Multi-sample with weak signals: capped at 0.60
- Multi-sample high-quality: 0.70-0.90

---

### **✅ CORRECT: Conservative Discounts**

**Location:** `ai_filter.py` lines 1936-1948

```python
if max_bids >= 5:
    resale_pct = 0.92  # 92% of observed
elif max_bids >= 3:
    resale_pct = 0.90  # 90% of observed
elif max_bids == 2:
    resale_pct = 0.88  # 88% of observed
else:  # max_bids == 1
    resale_pct = 0.82  # 82% of observed (STRONG PENALTY)

# Additional penalty if weak signals dominate
if has_weak_signals and max_bids < 3:
    resale_pct *= 0.95  # Extra 5% discount
```

✅ **Verified:** Discounts are conservative (82-92%), not optimistic

---

### **✅ CORRECT: No AI Hallucinations in Resale**

**Location:** `ai_filter.py` - market resale calculation is purely statistical

```python
# Line 1930: market_value = weighted_median(price_samples)
# Line 1950: resale_price = market_value * resale_pct
```

✅ **Verified:** Resale estimation uses only:

- Observed auction prices (current_price_ricardo)
- Weighted median calculation
- Conservative discount factors
- NO AI guessing involved

---

### **✅ CORRECT: No Asking-Price Logic**

**Location:** `ai_filter.py` lines 1813-1814

```python
# v7.2.2: IGNORE pure buy-now listings (no bids)
if not current or current <= 0 or bids == 0:
    continue
```

✅ **Verified:** Zero-bid listings (asking prices) are excluded

- Buy-now prices used only as upper bound sanity cap
- Never used as resale estimate

---

## WHAT SIGNALS ARE TRUSTED

### **✅ TRUSTED (High Confidence)**

1. **Auctions with ≥5 bids**
   - Weight: 1.00
   - Discount: 92%
   - Confidence contribution: Full

2. **Auctions with 3-4 bids**
   - Weight: 0.80
   - Discount: 90%
   - Confidence contribution: Full

3. **Multiple samples (≥3) with high bids**
   - Outliers removed (bottom 30%)
   - Weighted median used
   - Confidence: 0.70-0.90

---

### **⚠️ WEAK SIGNALS (Low Confidence)**

1. **Auctions with 2 bids**
   - Weight: 0.60
   - Discount: 88%
   - Not accepted as single sample

2. **Auctions with 1 bid (≥45% reference)**
   - Weight: 0.35 (never dominant)
   - Discount: 82%
   - Never accepted as single sample
   - Contributes max +0.10 to confidence

---

### **❌ REJECTED (Not Trusted)**

1. **Zero-bid listings** (asking prices)
2. **Start-price auctions** (≤1 CHF)
3. **Unrealistic low prices** (<20% reference, even with bids)
4. **1-bid listings <45% reference**
5. **Single 1-bid samples** (too weak)
6. **Low outliers** (<30% of max price in multi-sample)

---

## WHY THIS MATCHES HUMAN INTUITION

### **Human Intuition: "Many bids = real demand"**

✅ **System:** 5+ bids get full weight (1.00), high discount (92%)

### **Human Intuition: "Single bid might be a fluke"**

✅ **System:** 1-bid gets weak weight (0.35), strong penalty (82%)

### **Human Intuition: "Start prices don't mean anything"**

✅ **System:** Prices ≤1 CHF excluded, even with bids

### **Human Intuition: "Too cheap = something's wrong"**

✅ **System:** <20% of reference rejected, even with high bids

### **Human Intuition: "More data = more confidence"**

✅ **System:** Confidence scales with sample size and bid activity

### **Human Intuition: "Conservative estimate = safer"**

✅ **System:** 82-92% of observed (not 100%), extra penalty for weak signals

---

## REMAINING ISSUES TO FIX

### **Issue 1: Dead Code Removal**

**Files to modify:**

1. `db_pg_v2.py` - Remove `record_price_if_changed`, `get_price_history`, `get_product_resale_*`
2. `main.py` - Remove learned resale estimate fetching (lines 605-641)
3. `main.py` - Remove `record_price_if_changed` import

---

### **Issue 2: Misleading Comments**

**Update comments in:**

1. `ai_filter.py` line 13 - Remove "price_history is source of truth"
2. `main.py` - Update "PHASE 4.1c" comments to reflect live-market-first
3. Remove all "v7.x" version references

---

### **Issue 3: Bundle Logic Clarity**

**Add clear markers:**

1. `main.py` - Add "BUNDLES DISABLED" comment
2. `ai_filter.py` - Mark bundle functions as "OUT OF SCOPE"

---

## NEXT STEPS

1. ✅ Files deleted (41 .md, 8 .sql, 3 .py)
2. ⏳ Remove dead code (price_history, learned estimates)
3. ⏳ Update misleading comments
4. ⏳ Define strict test plan (3 runs, 5-6 products each)
5. ⏳ Execute test runs
6. ⏳ Quality gate assessment

---

## FILES KEPT (ACTIVE CODEBASE)

**Core Pipeline:**

- main.py
- ai_filter.py
- db_pg_v2.py
- config.py
- runtime_mode.py

**Extraction:**

- extraction/ai_extractor.py
- extraction/ai_extractor_batch.py
- extraction/ai_prompt.py
- extraction/bundle_classifier.py (disabled)

**Scrapers:**

- scrapers/ricardo.py
- scrapers/detail_scraper.py
- scrapers/browser_ctx.py

**Models:**

- models/extracted_product.py
- models/product_identity.py
- models/product_spec.py
- models/websearch_query.py
- models/bundle_types.py (disabled)

**Utils:**

- query_analyzer.py
- market_prices.py
- clarity_detector.py
- logger_utils.py
- utils\_\*.py

**Schema:**

- schema_v2.2_FINAL.sql

**Documentation:**

- README.md
- PRICING_ANALYSIS.md
- PHASE_4_1C_IMPLEMENTATION_SUMMARY.md

---

**Total files deleted:** 52  
**Total files kept:** ~40  
**Codebase reduction:** ~56%
