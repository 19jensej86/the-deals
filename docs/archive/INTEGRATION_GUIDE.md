# Integration Guide: Query-Agnostic Product Extraction

## 📋 Overview

This guide explains how to integrate the new query-agnostic product extraction architecture into `main.py`.

## 🏗️ Architecture Components

```
models/
├─ bundle_types.py          # BundleType enum + PricingMethod
├─ product_spec.py          # ProductSpec dataclass
├─ extracted_product.py     # ExtractedProduct dataclass
├─ product_identity.py      # ProductIdentity for deduplication
└─ websearch_query.py       # WebsearchQuery generation

extraction/
├─ ai_prompt.py             # System + user prompt templates
├─ ai_extractor.py          # AI extraction with Claude/OpenAI
└─ bundle_classifier.py     # Conservative bundle classification

pipeline/
├─ decision_gates.py        # Confidence thresholds + escalation logic
└─ pipeline_runner.py       # Main processing orchestration

logging/
├─ listing_logger.py        # Per-listing cost tracking
└─ run_logger.py            # Run-level statistics

tests/
└─ test_examples_p1_p4.py   # Verification tests
```

## 🔧 Integration into main.py

### Step 1: Import New Modules

Add these imports at the top of `main.py`:

```python
from pipeline.pipeline_runner import process_batch
from logging.run_logger import RunLogger
from models.websearch_query import generate_websearch_query
from models.bundle_types import get_pricing_method
```

### Step 2: Replace Current Extraction Logic

In `run_v9_pipeline()`, replace the current extraction logic with:

```python
def run_v9_pipeline(
    queries: List[str],
    query_analyses: Dict[str, Any],
    context,
    cfg,
    conn,
    global_stats: Dict[str, int],
    car_model: str,
    max_listings_per_query: Optional[int],
    run_id: str,
) -> List[Dict[str, Any]]:
    """
    v10 Pipeline: Query-agnostic product extraction with zero hallucinations.
    """
    logger = get_logger()
    
    # =========================================================================
    # PHASE 1: SCRAPE ALL QUERIES
    # =========================================================================
    logger.step_start(
        step_name="SCRAPING",
        what="Scraping Ricardo listings for all search queries",
        why="We need to collect all available listings to find good deals",
        uses_ai=False,
        uses_rules=True,
    )
    
    all_listings = []
    for query in queries:
        listings = scrape_ricardo_listings(query, max_listings_per_query)
        all_listings.extend(listings)
    
    logger.step_end(f"Scraped {len(all_listings)} listings")
    
    # =========================================================================
    # PHASE 2: QUERY-AGNOSTIC PRODUCT EXTRACTION
    # =========================================================================
    logger.step_start(
        step_name="PRODUCT_EXTRACTION",
        what="Extracting structured product data from listings",
        why="Need to understand products without query assumptions",
        uses_ai=True,
        uses_rules=False,
    )
    
    # Process batch with new pipeline
    extracted_products, run_logger = process_batch(
        listings=all_listings,
        run_id=run_id,
        detail_scraper=None,  # TODO: Integrate existing detail scraper
        vision_analyzer=None   # TODO: Integrate existing vision analyzer
    )
    
    logger.step_end(f"Extracted {len(extracted_products)} products")
    
    # Print cost breakdown
    run_logger.print_cost_breakdown()
    
    # =========================================================================
    # PHASE 3: WEBSEARCH QUERY GENERATION
    # =========================================================================
    logger.step_start(
        step_name="WEBSEARCH_PREPARATION",
        what="Generating optimized websearch queries",
        why="Need shop-optimized queries for price fetching",
        uses_ai=False,
        uses_rules=True,
    )
    
    websearch_queries = []
    for extracted in extracted_products:
        for product in extracted.products:
            query = generate_websearch_query(product)
            websearch_queries.append({
                "listing_id": extracted.listing_id,
                "product": product,
                "query": query
            })
    
    logger.step_end(f"Generated {len(websearch_queries)} websearch queries")
    
    # =========================================================================
    # PHASE 4: PRICE FETCHING (existing logic)
    # =========================================================================
    # TODO: Use websearch_queries for price fetching
    # TODO: Apply pricing methods based on bundle_type
    
    # =========================================================================
    # PHASE 5: DEAL EVALUATION (existing logic)
    # =========================================================================
    # TODO: Evaluate deals using extracted products
    
    return []  # TODO: Return deals
```

### Step 3: Integrate Detail Scraper

If you have an existing detail scraper, integrate it:

```python
from scrapers.detail_scraper import scrape_detail_page

# In process_batch call:
extracted_products, run_logger = process_batch(
    listings=all_listings,
    run_id=run_id,
    detail_scraper=lambda url: scrape_detail_page(url, context),
    vision_analyzer=None
)
```

### Step 4: Integrate Vision Analyzer

If you have vision analysis:

```python
from ai_filter import analyze_listing_with_vision

# In process_batch call:
extracted_products, run_logger = process_batch(
    listings=all_listings,
    run_id=run_id,
    detail_scraper=lambda url: scrape_detail_page(url, context),
    vision_analyzer=analyze_listing_with_vision
)
```

## 🧪 Testing

Run the verification tests:

```bash
cd c:\AI-Projekt\the-deals
python -m pytest tests/test_examples_p1_p4.py -v
```

Or run directly:

```bash
python tests/test_examples_p1_p4.py
```

Expected output:
```
=== TEST P1: iPhone (Single Product) ===
✅ P1 PASSED: No hallucinations, correct classification

=== TEST P2: Gym 80 (Quantity) ===
✅ P2 PASSED: No material hallucination, correct quantity classification

=== TEST P3: Playmobil (Unknown → Detail) ===
✅ P3 PASSED: Correctly marked as unknown, needs detail

=== TEST P4: Kettlebell (Price-Relevant Attr) ===
✅ P4 PASSED: Price-relevant attribute correctly kept

=== TEST P5: Pokémon (Bulk Lot) ===
✅ P5 PASSED: Correctly classified as BULK_LOT (not weight-based)

✅ ALL TESTS PASSED
```

## 📊 Monitoring & Logging

The new system provides transparent logging:

```python
# After processing
run_logger.print_cost_breakdown()
```

Output:
```
============================================================
COST BREAKDOWN - Run 20260113_001002
============================================================
AI Extraction:    $0.0234
Websearch:        $0.0000
Detail Scraping:  $0.0056
Vision:           $0.0012
------------------------------------------------------------
TOTAL:            $0.0302
============================================================

📊 STATISTICS
Total Listings:        24
Ready for Pricing:     18
Needed Detail:         4
Needed Vision:         1
Skipped (too unclear): 1

🤖 AI USAGE
AI Calls:              24
Websearches:           18

📈 RATES
Skip Rate:             4.2%
Detail Scraping Rate:  16.7%
Vision Rate:           4.2%
```

## 🔑 Key Principles

### ✅ DO

1. **Query-Agnostic**: AI never sees search query
2. **Zero Hallucinations**: Only extract explicit mentions
3. **Conservative Escalation**: Detail → Vision → Skip
4. **Transparent Costs**: Log every AI/websearch call
5. **Explicit Uncertainty**: `unknown` is valid

### ❌ DON'T

1. **No Implicit Assumptions**: Brand ≠ Material
2. **No Domain Heuristics**: No "Fitness = Weight" logic
3. **No Query Usage**: Product extraction independent of query
4. **No Guessing**: When uncertain → escalate or skip

## 🚀 Expected Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Websearch Success | 52% | 75%+ | +44% |
| NULL variant_key | 12.5% | 0% | -100% |
| Hallucinated Specs | ~20% | 0% | -100% |
| Bundle Misclass | 25% | <5% | -80% |
| Overall Confidence | 51/100 | 80/100 | +57% |

## 📝 Migration Checklist

- [ ] Import new modules into `main.py`
- [ ] Replace extraction logic in `run_v9_pipeline()`
- [ ] Integrate existing detail scraper
- [ ] Integrate existing vision analyzer (if available)
- [ ] Run verification tests
- [ ] Test with real queries (iPhone, Bosch, Playmobil, etc.)
- [ ] Verify cost tracking works
- [ ] Verify no hallucinations in production
- [ ] Monitor skip rate (should be 5-10%)
- [ ] Monitor detail scraping rate (should be 15-25%)

## 🆘 Troubleshooting

### Issue: AI extraction returns empty products

**Solution**: Check API keys are set:
```bash
echo $ANTHROPIC_API_KEY
echo $OPENAI_API_KEY
```

### Issue: Tests fail with import errors

**Solution**: Ensure you're in the project root:
```bash
cd c:\AI-Projekt\the-deals
python tests/test_examples_p1_p4.py
```

### Issue: High skip rate (>15%)

**Possible causes**:
- Confidence thresholds too high
- Detail scraper not integrated
- Vision analyzer not integrated

**Solution**: Check `pipeline/decision_gates.py` thresholds

### Issue: Hallucinated specs appearing

**Solution**: This should NOT happen. If it does:
1. Check AI prompt in `extraction/ai_prompt.py`
2. Verify SYSTEM_PROMPT is used
3. Add test case to `tests/test_examples_p1_p4.py`
4. Report as critical bug

## 📞 Support

For questions or issues, refer to:
- Architecture document (previous response)
- Test cases in `tests/test_examples_p1_p4.py`
- Inline documentation in each module
