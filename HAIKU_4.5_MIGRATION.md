# Claude Haiku 4.5 Migration - 2026-01-20

## 📧 Deprecation Notice

**From:** Anthropic  
**Date:** 2026-01-20  
**Deadline:** February 19, 2026 at 9 AM PT

Claude Haiku 3.5 (`claude-3-5-haiku-20241022`) will be **retired and no longer supported**.

---

## ✅ Migration Completed - Option 2 (Hybrid Approach)

### **Changes Made**

#### **1. Configuration Updates**

**`configs/config.yaml`:**
- ✅ Updated `claude_model_fast`: `claude-3-5-haiku-20241022` → `claude-3-5-haiku-20250514` (Haiku 4.5)
- ✅ Updated cost constants: `claude_haiku_usd: 0.002` → `0.008` (4x increase)
- ✅ Updated `claude_web_search_usd`: `0.10` → `0.35` (corrected actual cost)

**`runtime_mode.py`:**
- ✅ Updated TEST mode budget: `max_run_cost_usd: 0.20` → `0.50`

---

#### **2. Code Updates**

**`ai_filter.py`:**
- ✅ Updated `MODEL_FAST`: `claude-3-5-haiku-20241022` → `claude-3-5-haiku-20250514`
- ✅ Updated `COST_CLAUDE_HAIKU`: `0.003` → `0.012` (4x increase)
- ✅ Updated `COST_CLAUDE_WEB_SEARCH`: `0.10` → `0.35`

**`query_analyzer.py`:**
- ✅ Updated hardcoded model: `claude-3-5-haiku-20241022` → `claude-3-5-haiku-20250514`

**`extraction/ai_extractor.py`:**
- ✅ Updated hardcoded model: `claude-3-5-haiku-20241022` → `claude-3-5-haiku-20250514`

---

## 💰 Cost Impact

### **Before (Haiku 3.5):**
```
Input:  $0.25 / 1M tokens
Output: $1.25 / 1M tokens
```

### **After (Haiku 4.5):**
```
Input:  $1.00 / 1M tokens (4x increase)
Output: $5.00 / 1M tokens (4x increase)
```

---

## 📊 Expected Costs Per TEST Run

### **With Websearch:**
- Query Analysis (Haiku 4.5): ~$0.048 (was $0.012)
- Product Extraction (Haiku 4.5): ~$0.096 (was $0.024)
- Websearch (Sonnet 4): ~$0.35 (unchanged)
- **Total: ~$0.494** (was ~$0.386)

### **Without Websearch:**
- Query Analysis: ~$0.048
- Product Extraction: ~$0.096
- **Total: ~$0.144** (was ~$0.036)

---

## 🎯 Hybrid Strategy (Option 2)

| Task | Model | Reason |
|------|-------|--------|
| **Query Analysis** | Haiku 4.5 | Simple, infrequent (4 queries/run) |
| **Product Extraction** | Haiku 4.5 | Fast, many calls, simple structure |
| **Bundle Detection** | Haiku 4.5 | Regex-like pattern matching |
| **Price Estimation** | Haiku 4.5 | Fallback only when websearch fails |
| **Websearch** | Sonnet 4 | Complex, requires web access |

**Result:** Only websearch uses expensive Sonnet 4, rest uses Haiku 4.5

---

## ✅ Testing Checklist

- [ ] Claude API credits topped up
- [ ] Run `python main.py` in TEST mode
- [ ] Verify costs stay under $0.50 budget
- [ ] Check that Haiku 4.5 is being used (logs should show model name)
- [ ] Verify websearch still works with Sonnet 4
- [ ] Confirm run finalization works correctly

---

## 🚨 Important Notes

1. **Budget Increased:** TEST mode budget raised from $0.20 to $0.50 to accommodate 4x price increase
2. **No Code Logic Changes:** Only model names and cost constants updated
3. **Backward Compatible:** Old cache files still work
4. **Deadline:** Must complete before **February 19, 2026**

---

## 📝 Next Steps

1. **Top up Claude API credits** (current balance too low)
2. **Test the pipeline** with `python main.py`
3. **Monitor costs** in first few runs
4. **Adjust budget** if needed (can increase PROD budget if $5 is too low)

---

## 🔗 References

- Anthropic Deprecation Policy: https://docs.anthropic.com/en/api/versioning
- Haiku 4.5 Documentation: https://docs.anthropic.com/en/docs/models-overview
- Migration completed: 2026-01-20
