# STRICT TEST PLAN - LIVE-MARKET PRICING VALIDATION

**Date:** 2026-01-31  
**Context:** Database reset complete. Clean state. Live-market-first pricing only.  
**Goal:** Validate pricing logic with real money at stake. Conservative > optimistic.

---

## TEST CONSTRAINTS

### **MANDATORY RULES**
- ✅ **3 consecutive runs** (no more, no less)
- ✅ **5-6 DIFFERENT products per run** (no duplicates across runs)
- ✅ **NO bundles** (out of scope)
- ✅ **NO sets** (out of scope)
- ✅ **Single-product listings only**

### **CATEGORIES**
1. **Electronics** (phones, headphones, watches)
2. **Fitness equipment** (single items: dumbbells, kettlebells, resistance bands)

### **FORBIDDEN**
- ❌ No bundles or sets
- ❌ No multi-item listings
- ❌ No "lot of X items"
- ❌ No accessories without clear standalone value

---

## RUN 1: ELECTRONICS (HIGH-VALUE)

### **Products to Search**
1. Apple iPhone 12 mini
2. Apple AirPods Pro 2
3. Samsung Galaxy Watch 4
4. Sony WH-1000XM4
5. Apple iPad 9th Gen

### **Expected Outputs**
For each deal found, capture:
```json
{
  "product": "Apple AirPods Pro 2",
  "listing_title": "...",
  "current_price": 180,
  "resale_estimate": 220,
  "expected_profit": 25,
  "profit_margin": 13.9,
  "confidence": 0.65,
  "price_source": "single_high_quality_auction",
  "sample_size": 1,
  "bids_distribution": [5],
  "price_distribution": [200],
  "excluded_listings": [],
  "weak_signal_listings": [],
  "validation": {
    "bids_check": "PASS (≥3)",
    "price_check": "PASS (>=40%)",
    "momentum_check": "PASS",
    "discount_applied": "90%",
    "sample_quality": "moderate"
  },
  "strategy": "bid",
  "deal_score": 6.5
}
```

### **Quality Checks**
- [ ] Are resale estimates 82-92% of observed prices?
- [ ] Are confidence scores realistic (0.50-0.90)?
- [ ] Are 1-bid listings marked as weak signals?
- [ ] Are profit margins ≤50%?
- [ ] Are excluded listings documented with reasons?

---

## RUN 2: FITNESS EQUIPMENT (MID-VALUE)

### **Products to Search**
1. Kettlebell 16kg
2. Dumbbells adjustable
3. Resistance bands set (single product, not bundle)
4. Yoga mat premium
5. Pull-up bar
6. Foam roller

### **Expected Outputs**
Same structure as Run 1, but expect:
- Lower profit margins (10-20% typical for fitness)
- More stable pricing (less variance)
- Potentially fewer deals (niche market)

### **Quality Checks**
- [ ] Are fitness items priced conservatively?
- [ ] Are heavy items (kettlebells) flagged for transport costs?
- [ ] Are generic items (yoga mat) filtered correctly?
- [ ] Are profit margins realistic for fitness category?

---

## RUN 3: MIXED ELECTRONICS (LOW-VALUE)

### **Products to Search**
1. Apple Magic Keyboard
2. Logitech MX Master 3
3. USB-C cables (single item, not bundle)
4. Anker PowerBank
5. Philips Hue bulbs (single bulb, not set)

### **Expected Outputs**
Expect:
- Lower absolute profits (5-15 CHF)
- Higher rejection rate (accessories often overpriced)
- More "skip" strategies
- Lower confidence scores

### **Quality Checks**
- [ ] Are low-value accessories correctly filtered?
- [ ] Are profit margins still realistic despite low absolute profit?
- [ ] Are deals with <10 CHF profit marked appropriately?
- [ ] Are generic accessories (cables) handled correctly?

---

## OUTPUT FORMAT (PER RUN)

### **1. Deals Export**
File: `run_X_deals.json`

Required fields for each deal:
- product, listing_title, url
- current_price, resale_estimate, expected_profit, profit_margin
- confidence, price_source, sample_size
- bids_distribution, price_distribution
- excluded_listings, weak_signal_listings
- validation (all checks)
- strategy, deal_score

### **2. Summary Stats**
File: `run_X_stats.json`

```json
{
  "run_id": "...",
  "total_listings": 50,
  "total_deals": 8,
  "profitable_deals": 5,
  "avg_profit": 22.50,
  "avg_margin": 18.3,
  "avg_confidence": 0.68,
  "price_source_breakdown": {
    "single_high_quality_auction": 3,
    "auction_demand_moderate": 2,
    "auction_demand_weak_signals": 0,
    "web_derived": 2,
    "ai_fallback": 1
  },
  "strategy_breakdown": {
    "bid": 4,
    "watch": 1,
    "skip": 3
  }
}
```

### **3. Excluded Listings Report**
File: `run_X_excluded.json`

For each excluded listing, document:
- Why it was excluded (zero bids, unrealistic price, start price, etc.)
- What filters caught it
- Original price and bids

---

## QUALITY GATE CRITERIA

### **PASS Criteria (Deal is Trustworthy)**
✅ Confidence ≥ 0.55  
✅ Profit margin ≤ 30%  
✅ Expected profit ≤ 100 CHF (for testing)  
✅ Price source = live market (not AI fallback)  
✅ Sample size ≥ 1 with ≥3 bids OR ≥2 samples  
✅ Clear observability (can verify logic)  

### **BORDERLINE (Human Review Only)**
⚠️ Confidence 0.50-0.55  
⚠️ Profit margin 25-30%  
⚠️ Weak signals present but not dominant  
⚠️ Single sample with 3-4 bids  

### **REJECT (Skip Deal)**
❌ Confidence < 0.50  
❌ Profit margin > 30%  
❌ Price source = AI fallback  
❌ Single 1-bid sample  
❌ Unrealistic resale estimate  

---

## POST-RUN ANALYSIS

### **For Each Run, Answer:**

1. **Deal Quality**
   - How many deals passed quality gate?
   - How many were borderline?
   - How many were rejected?

2. **Pricing Realism**
   - Are resale estimates conservative (82-92%)?
   - Are profit margins realistic for category?
   - Are confidence scores aligned with signal quality?

3. **Observability**
   - Can you see which listings were used?
   - Can you see which were excluded and why?
   - Can you verify the pricing logic?

4. **Red Flags**
   - Any fantasy prices (>100% margin)?
   - Any AI hallucinations?
   - Any misleading confidence scores?
   - Any 1-bid listings dominating pricing?

5. **Trust Assessment**
   - Would YOU bid on these deals with real money?
   - Which specific deals are trustworthy?
   - Which need human review?
   - Which should be skipped?

---

## FINAL QUALITY GATE (AFTER 3 RUNS)

### **Answer Honestly:**

1. **Overall Trust**
   - Would you trust this system with 50 CHF test bids?
   - Would you trust it with 100 CHF bids?
   - Would you trust it with 200+ CHF bids?

2. **Deal Quality Distribution**
   - What % of deals are clearly good?
   - What % are borderline (human review)?
   - What % should be skipped?

3. **Remaining Issues**
   - Any fantasy pricing still present?
   - Any unrealistic margins?
   - Any misleading signals?
   - Any bugs or logic errors?

4. **Concrete Fixes Needed**
   - If something is NOT trustworthy, state it clearly
   - Propose specific fix (no scope creep)
   - Estimate impact of fix

---

## SUCCESS CRITERIA

### **Minimum Requirements**
- ✅ At least 5 trustworthy deals across 3 runs
- ✅ No fantasy prices (>50% margin)
- ✅ No AI hallucinations in resale estimates
- ✅ Clear observability for all deals
- ✅ Conservative pricing (82-92% discounts)

### **Ideal Outcome**
- ✅ 10-15 trustworthy deals across 3 runs
- ✅ Avg confidence 0.60-0.75
- ✅ Avg margin 15-25%
- ✅ Clear separation: good / borderline / skip
- ✅ Full transparency (can verify every decision)

---

## EXECUTION CHECKLIST

### **Before Each Run**
- [ ] Database is clean (no stale data)
- [ ] Price cache is cleared
- [ ] Config is correct (mode, budget, etc.)
- [ ] Search queries are prepared

### **During Each Run**
- [ ] Monitor console output for errors
- [ ] Check pricing logic is being applied
- [ ] Verify exclusions are logged
- [ ] Confirm no bundles are evaluated

### **After Each Run**
- [ ] Export deals.json
- [ ] Export stats.json
- [ ] Export excluded.json
- [ ] Review quality metrics
- [ ] Document any issues

### **After All 3 Runs**
- [ ] Aggregate results
- [ ] Analyze trends
- [ ] Identify patterns
- [ ] Provide honest assessment
- [ ] Propose fixes if needed

---

## BENCHMARK: HUMAN INTUITION

**For each deal, ask:**
- Would a human marketplace expert bid on this?
- Is the profit margin realistic for Swiss second-hand?
- Is the confidence score aligned with the evidence?
- Are there any red flags a human would catch?

**If the answer is NO to any question:**
- Document the issue
- Explain why it's wrong
- Propose a fix

---

## FINAL DELIVERABLE

After 3 runs, provide:

1. **Summary Report** (1 page)
   - Total deals found
   - Quality distribution (good / borderline / skip)
   - Trust level (YES / NO / CONDITIONAL)
   - Remaining issues
   - Proposed fixes

2. **Deal Examples** (3-5 deals)
   - Show best deals (clearly trustworthy)
   - Show borderline deals (human review needed)
   - Show rejected deals (why they were skipped)

3. **Honest Assessment**
   - Would YOU invest real money?
   - Under what conditions?
   - What's missing for full trust?

---

**Remember:** Quality > quantity. Conservative > optimistic. Human intuition is the benchmark.
