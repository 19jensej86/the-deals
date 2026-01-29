# After-Run Analysis Guide

## Overview

This guide explains all files exported after each pipeline run for comprehensive analysis without requiring database or console access.

## Exported Files

### 1. **last_run.log**

- **Purpose**: Complete console output from the run
- **Contains**:
  - Step-by-step execution logs
  - AI call details and costs
  - Error messages and warnings
  - Performance metrics
  - Cost breakdowns
- **Use for**: Understanding what happened during the run, debugging issues

### 2. **last_run_deals.json** ✨ NEW

- **Purpose**: All deals found in the latest run (v2.2 schema)
- **Contains**:
  - Deal metadata (profit, score, strategy)
  - Product information
  - Pricing data (new_price, resale_price, expected_profit)
  - Price sources (web search, AI estimate, etc.)
  - Listing details (bids, time remaining, location)
- **Use for**: Analyzing deal quality, profit distribution, price source effectiveness

### 3. **last_run_deals.csv**

- **Purpose**: Same as JSON but in CSV format for Excel/spreadsheet analysis
- **Use for**: Quick filtering, sorting, pivot tables

### 4. **last_run_bundles.json** ✨ NEW

- **Purpose**: All bundle deals found in the latest run
- **Contains**:
  - Bundle metadata
  - Component breakdown (what's in the bundle)
  - Component pricing
  - Bundle profit calculations
- **Use for**: Analyzing bundle detection quality, component pricing accuracy

### 5. **last_run_bundles.csv**

- **Purpose**: Same as JSON but in CSV format
- **Use for**: Quick bundle analysis in spreadsheets

### 6. **last_run_products.json** ✨ NEW

- **Purpose**: All unique products identified in the run
- **Contains**:
  - Product IDs and keys
  - Brand, model, category
  - Display names
  - Variant information
- **Use for**: Understanding product normalization, checking for duplicates

### 7. **last_run_stats.json** ✨ NEW

- **Purpose**: Comprehensive run statistics and metadata
- **Contains**:
  - Run metadata (start/end time, status, cost)
  - Deal statistics (total, profitable, avg profit)
  - Bundle statistics
  - Price source breakdown
  - Strategy breakdown (buy_now, watch, skip, etc.)
- **Use for**: High-level run quality assessment, cost analysis

### 8. **last_run_listings.json** (Legacy)

- **Purpose**: Raw listings data (backwards compatibility)
- **Contains**: All scraped listings with evaluation results
- **Note**: This is the old format, use deals/bundles JSON for new analysis

### 9. **analysis_data.json**

- **Purpose**: Quality metrics and recommendations
- **Contains**:
  - Quality score (0-100)
  - Issue detection (suspicious prices, bundle problems)
  - Recommendations for improvement
- **Use for**: Quick quality check, identifying problems

## Analysis Workflow

### Step 1: Check Run Success

```
1. Read last_run.log (end of file)
2. Look for "✅ Pipeline completed successfully!"
3. Check for any errors or warnings
```

### Step 2: Review Statistics

```
1. Read last_run_stats.json
2. Check run_metadata.status = "completed"
3. Review deal_statistics (total, profitable, avg_profit)
4. Check price_source_breakdown (web vs AI fallback)
5. Review cost_usd
```

### Step 3: Analyze Deal Quality

```
1. Read last_run_deals.json
2. Sort by expected_profit DESC
3. Check top deals for realism
4. Verify price_source distribution
5. Look for suspicious patterns
```

### Step 4: Check Bundle Detection

```
1. Read last_run_bundles.json
2. Review component_count and components
3. Check if component prices are realistic
4. Verify bundle profit calculations
```

### Step 5: Identify Issues

```
1. Read analysis_data.json
2. Check quality_score
3. Review issues.suspicious_prices
4. Review issues.bundle_default_prices
5. Read recommendations
```

## Key Metrics to Check

### Cost Efficiency

- **Target**: < $0.02 per listing in TEST mode
- **Check**: last_run_stats.json → run_metadata.cost_usd
- **Good**: Batch extraction used (1 AI call for 30 listings)
- **Bad**: Individual extraction (30 AI calls)

### Price Source Quality

- **Best**: web\_\* sources (real market data)
- **OK**: query_baseline, buy_now_fallback
- **Worst**: ai_estimate (AI guessing)
- **Check**: last_run_stats.json → price_source_breakdown

### Deal Quality

- **Profitable**: expected_profit > 20 CHF
- **Very Good**: expected_profit > 50 CHF
- **Excellent**: expected_profit > 100 CHF
- **Check**: last_run_deals.json → expected_profit

### Bundle Detection

- **Good**: Bundles have 2+ components with realistic prices
- **Bad**: Components have default 50 CHF prices
- **Check**: last_run_bundles.json → components

## Common Issues

### Issue 1: High AI Fallback Rate

**Symptom**: Most deals have price_source = "ai_estimate"
**Cause**: Web search not working or disabled
**Fix**: Enable web search in PROD mode, check API keys

### Issue 2: Unrealistic Profits

**Symptom**: Deals with 500+ CHF profit
**Cause**: Wrong new_price (outdated model, wrong product)
**Fix**: Check query_analyzer.py fallback prices

### Issue 3: Bundle Default Prices

**Symptom**: Bundle components all cost 50 CHF
**Cause**: AI bundle price estimation failing
**Fix**: Check Claude model version in bundle estimator

### Issue 4: No Deals Found

**Symptom**: last_run_deals.json is empty
**Cause**: Too aggressive filtering or no profitable listings
**Fix**: Check scraping results, lower profit threshold

## Quick Analysis Commands

### Count Deals by Strategy

```python
import json
with open('last_run_deals.json') as f:
    deals = json.load(f)
strategies = {}
for d in deals:
    s = d['recommended_strategy']
    strategies[s] = strategies.get(s, 0) + 1
print(strategies)
```

### Find Top 10 Deals

```python
import json
with open('last_run_deals.json') as f:
    deals = json.load(f)
top = sorted(deals, key=lambda x: x['expected_profit'], reverse=True)[:10]
for d in top:
    print(f"{d['title']}: {d['expected_profit']} CHF")
```

### Check Price Source Distribution

```python
import json
with open('last_run_stats.json') as f:
    stats = json.load(f)
print(stats['price_source_breakdown'])
```

## Cascade Analysis Prompt

When asking Cascade to analyze a run, use:

```
Analyze the last run using the after-run files:
1. Check if run completed successfully
2. Review deal quality and quantity
3. Analyze costs and efficiency
4. Check for any issues or problems
5. Provide recommendations
```

Cascade will automatically read:

- last_run.log
- last_run_stats.json
- last_run_deals.json
- last_run_bundles.json
- analysis_data.json

And provide a comprehensive analysis without needing database access.

## File Locations

All files are saved in the project root:

```
c:\AI-Projekt\the-deals\
├── last_run.log
├── last_run_deals.json
├── last_run_deals.csv
├── last_run_bundles.json
├── last_run_bundles.csv
├── last_run_products.json
├── last_run_stats.json
├── last_run_listings.json (legacy)
└── analysis_data.json
```

## Version History

- **v1.0** (Jan 20): Basic listings export
- **v2.0** (Jan 28): Comprehensive export system with deals, bundles, products, and stats
