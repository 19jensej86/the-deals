"""
DealFinder Main Pipeline - v7.2 (Improved Accessory Filter)
============================================================
Changes from v7.1:
- HARDCODED accessory pre-filter BEFORE AI-generated keywords
- Query-aware: "Armband" query won't filter armbands
- Category-aware: Fitness "Set" = bundle, not accessory!
- Position-aware: "Armband für Garmin" vs "Garmin mit Armband"
- Better statistics: shows how many filtered by each method

Pipeline Steps:
1. Load config
2. Connect to database (auto-migrate schema)
3. Optionally clear DB (testing mode)
4. Analyze all queries with AI (cached 30 days)
5. Start browser
6. For each query:
   a. Scrape Ricardo SERP
   b. PRE-FILTER 1: Hardcoded accessory detection (v7.2!)
   c. PRE-FILTER 2: AI-generated accessory keywords
   d. PRE-FILTER 3: Defect keywords
   e. Cluster listings into variants
   f. Calculate market resale from auctions with bids
   g. Fetch variant info (new prices, transport)
   h. Evaluate each listing (with global sanity checks!)
   i. Save to database
7. Scrape detail pages for top deals
8. Generate HTML report
9. Show AI cost summary
"""

import traceback
import sys
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from io import StringIO

from playwright.sync_api import sync_playwright

from config import load_config, print_config_summary
from db_pg import (
    get_conn, 
    ensure_schema, 
    upsert_listing, 
    cleanup_old_listings,
    clear_listings,
    record_price_if_changed,
    clear_expired_market_data,
    clear_stale_market_for_variant,
    update_listing_details,
)
from scrapers.browser_ctx import (
    ensure_chrome_closed,
    clone_profile,
    cleanup_profile,
    launch_persistent_context,
)
from scrapers.ricardo import search_ricardo
from utils_time import parse_ricardo_end_time
from utils_text import (
    contains_excluded_terms, 
    normalize_whitespace,
    is_accessory_title,
    detect_category,
)

from query_analyzer import (
    analyze_queries,
    clear_query_cache,
    get_min_realistic_price,
    get_auction_multiplier,
    get_defect_keywords,
    get_accessory_keywords,
    get_category,
)

from ai_filter import (
    apply_config,
    apply_ai_budget_from_cfg,
    reset_run_cost,
    get_run_cost_summary,
    get_day_cost_summary,
    save_day_cost,
    clear_all_caches,
    calculate_all_market_resale_prices,
    fetch_variant_info_batch,
    evaluate_listing_with_ai,
)

# v9: Product Extraction Pipeline
try:
    from product_extractor import (
        process_query_listings,
        build_global_product_list,
    )
    V9_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ v9 product_extractor not available: {e}")
    V9_AVAILABLE = False

# v9: Clarity Detection
try:
    from clarity_detector import (
        analyze_listing_clarity,
        filter_unclear_listings,
        process_vision_results,
    )
    from scrapers.detail_scraper import scrape_unclear_listings
    from ai_filter import batch_analyze_with_vision
    CLARITY_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ Clarity detection not available: {e}")
    CLARITY_AVAILABLE = False


# ==============================================================================
# v9 PIPELINE HELPER FUNCTIONS
# ==============================================================================

def run_v9_pipeline(
    queries: List[str],
    query_analyses: Dict[str, Any],
    context,
    cfg,
    conn,
    global_stats: Dict[str, int],
    car_model: str,
    max_listings_per_query: Optional[int],
) -> List[Dict[str, Any]]:
    """
    v9 Pipeline: Global product deduplication for cost optimization.
    
    Flow:
    1. PHASE 1: Scrape all queries, collect listings
    2. PHASE 2: Extract products from all listings (with deduplication)
    3. PHASE 3: One batch websearch for all unique products
    4. PHASE 4: Evaluate all listings using global price cache
    
    Returns:
        List of deals for detail scraping
    """
    all_deals_for_detail = []
    
    # =========================================================================
    # PHASE 1: SCRAPE ALL QUERIES
    # =========================================================================
    log_section("v9 PHASE 1: Scraping All Queries")
    
    all_listings_by_query: Dict[str, List[Dict[str, Any]]] = {}
    query_categories: Dict[str, str] = {}
    
    for query in queries:
        print(f"\n🔍 Scraping: {query}")
        
        query_analysis = query_analyses.get(query)
        
        # Get category
        if query_analysis:
            category = get_category(query_analysis)
        else:
            category = detect_category(query)
        query_categories[query] = category
        
        # Scrape listings
        listings = []
        skipped_count = 0
        
        try:
            for listing in search_ricardo(
                query=query,
                context=context,
                ua=cfg.general.user_agent,
                timeout_sec=cfg.general.request_timeout_sec,
                max_pages=cfg.general.max_pages_list,
            ):
                global_stats["total_scraped"] += 1
                
                title = listing.get("title") or ""
                normalized_title = normalize_whitespace(title)
                title_lower = normalized_title.lower()
                
                # PRE-FILTERS (same as v7)
                if contains_excluded_terms(title_lower, cfg.general.exclude_terms):
                    global_stats["skipped_exclude"] += 1
                    skipped_count += 1
                    continue
                
                if is_accessory_title(normalized_title, query=query, category=category):
                    global_stats["skipped_hardcoded_accessory"] += 1
                    skipped_count += 1
                    continue
                
                # AI accessory keywords filter
                ai_accessory_kw = get_accessory_keywords(query_analysis)
                if ai_accessory_kw:
                    if category.lower() in ["fitness", "sport"]:
                        ai_accessory_kw = [kw for kw in ai_accessory_kw 
                                           if kw.lower() not in ["set", "stange", "scheibe", "halterung"]]
                    
                    # Check bundle indicator
                    is_bundle_with_acc = False
                    for indicator in ["inkl.", "inkl ", "inklusive", " mit ", "+ ", "samt ", "plus "]:
                        if indicator in title_lower:
                            indicator_pos = title_lower.find(indicator)
                            for kw in ai_accessory_kw:
                                if title_lower.find(kw.lower()) > indicator_pos:
                                    is_bundle_with_acc = True
                                    break
                        if is_bundle_with_acc:
                            break
                    
                    if not is_bundle_with_acc and contains_excluded_terms(title_lower, ai_accessory_kw):
                        global_stats["skipped_ai_accessory"] += 1
                        skipped_count += 1
                        continue
                
                # Defect filter
                defect_kw = get_defect_keywords(query_analysis)
                if defect_kw and contains_excluded_terms(title_lower, defect_kw):
                    global_stats["skipped_defect"] += 1
                    skipped_count += 1
                    continue
                
                # Store query reference for later
                listing["_query"] = query
                listing["_category"] = category
                listings.append(listing)
                global_stats["sent_to_ai"] += 1
                
                # Limit check
                if max_listings_per_query and len(listings) >= max_listings_per_query:
                    print(f"   🛑 Reached limit ({max_listings_per_query})")
                    break
                    
        except Exception as e:
            print(f"   ❌ Scraping error: {e}")
            continue
        
        all_listings_by_query[query] = listings
        print(f"   ✅ {len(listings)} listings (filtered {skipped_count})")
    
    # Count totals
    total_listings = sum(len(lst) for lst in all_listings_by_query.values())
    print(f"\n📦 Total: {total_listings} listings from {len(queries)} queries")
    
    if total_listings == 0:
        print("⚠️ No listings found across all queries")
        return []
    
    # =========================================================================
    # PHASE 1.5: CLARITY DETECTION & SMART DETAIL SCRAPING
    # =========================================================================
    clarity_enabled = getattr(cfg.general, "clarity_detection_enabled", False)
    max_unclear_scrapes = getattr(cfg.general, "max_unclear_detail_scrapes", 10)
    max_vision_clarity = getattr(cfg.general, "max_vision_for_clarity", 5)
    
    if clarity_enabled and CLARITY_AVAILABLE:
        log_section("v9 PHASE 1.5: Clarity Detection")
        
        # Flatten all listings for clarity check
        all_flat = [l for listings in all_listings_by_query.values() for l in listings]
        
        # Filter into clear and unclear
        clear_listings, unclear_listings = filter_unclear_listings(
            all_flat,
            max_unclear=max_unclear_scrapes + 10,  # Get a bit more for prioritization
        )
        
        print(f"\n📊 Clarity Analysis:")
        print(f"   Clear titles:   {len(clear_listings)}")
        print(f"   Unclear titles: {len(unclear_listings)}")
        
        if unclear_listings and max_unclear_scrapes > 0:
            # Scrape detail pages for unclear listings
            print(f"\n🔍 Scraping detail pages for {min(len(unclear_listings), max_unclear_scrapes)} unclear listings...")
            
            now_clear, still_unclear = scrape_unclear_listings(
                unclear_listings=unclear_listings,
                context=context,
                max_pages=max_unclear_scrapes,
            )
            
            # Vision analysis for still-unclear listings
            if still_unclear and max_vision_clarity > 0:
                print(f"\n👁️ Vision analysis for {min(len(still_unclear), max_vision_clarity)} still-unclear listings...")
                still_unclear = batch_analyze_with_vision(
                    listings=still_unclear,
                    max_vision_calls=max_vision_clarity,
                )
                
                # Convert vision results to improved titles
                # e.g. "iPhone" → "Apple iPhone 12 Mini"
                # e.g. "Krafttraining Set" → bundle with 3 items
                process_vision_results(still_unclear)
            
            # Update the original listings in all_listings_by_query
            # (they're the same objects, so updates propagate automatically)
            
            enriched_count = len(now_clear) + len([l for l in still_unclear if l.get("_vision_result")])
            print(f"\n✅ Enriched {enriched_count} unclear listings with additional data")
    
    # =========================================================================
    # PHASE 2: PRODUCT EXTRACTION & DEDUPLICATION
    # =========================================================================
    log_section("v9 PHASE 2: Product Extraction & Deduplication")
    
    all_listing_products = []
    
    for query, listings in all_listings_by_query.items():
        if not listings:
            continue
            
        category = query_categories[query]
        print(f"\n🔧 Processing {len(listings)} listings for '{query}' (category: {category})")
        
        # Convert listings to format expected by product_extractor
        # Use vision-improved title if available (e.g. "iPhone" → "Apple iPhone 12 Mini")
        listing_dicts = []
        for l in listings:
            # Check for vision-improved title
            title = l.get("_vision_title") or l.get("title", "")
            
            listing_dicts.append({
                "listing_id": l.get("listing_id", ""),
                "title": title,
                "description": l.get("description", ""),
                # Pass bundle info from vision if detected
                "_vision_bundle_titles": l.get("_vision_bundle_titles"),
                "_is_bundle": l.get("_is_bundle", False),
            })
        
        # Extract products
        listing_products = process_query_listings(query, listing_dicts, category)
        all_listing_products.extend(listing_products)
        
        # Assign product keys back to listings
        for lp in listing_products:
            for listing in listings:
                if listing.get("listing_id") == lp.listing_id:
                    listing["_products"] = lp.products
                    listing["_is_bundle"] = lp.is_bundle
                    # Use first product's key as variant_key for compatibility
                    if lp.products:
                        listing["variant_key"] = lp.products[0].product_key
                        listing["_cleaned_title"] = lp.products[0].display_name
                        # v9.0: Log ALL title cleanups (before → after)
                        original = listing.get("title", "")
                        cleaned = lp.products[0].display_name
                        print(f"   🔧 '{original}' → '{cleaned}'")
                    break
    
    # Build global product list
    global_products = build_global_product_list(all_listing_products)
    
    print(f"\n📊 Deduplication Results:")
    print(f"   Raw listings:     {total_listings}")
    print(f"   Unique products:  {len(global_products)}")
    print(f"   Dedup rate:       {(1 - len(global_products)/max(total_listings, 1))*100:.0f}%")
    
    # =========================================================================
    # PHASE 3: PRICE FETCHING (ONE BATCH FOR ALL!)
    # =========================================================================
    log_section("v9 PHASE 3: Global Price Fetching")
    
    # Flatten all listings for market calculation
    all_listings_flat = [l for listings in all_listings_by_query.values() for l in listings]
    
    # v9: Create mapping from product_key (hash) to display_name (searchable)
    # This is critical - web search needs readable names, not hashes!
    key_to_name = {pk: p.display_name for pk, p in global_products.items()}
    name_to_key = {p.display_name: pk for pk, p in global_products.items()}
    
    # Use display_names for web search
    display_names = list(key_to_name.values())
    
    print(f"\n📦 Product dedup summary:")
    for name in display_names[:5]:
        print(f"   • {name}")
    if len(display_names) > 5:
        print(f"   ... and {len(display_names) - 5} more")
    
    # 3a) Market-based resale (from competing Ricardo listings)
    print(f"\n📈 Calculating market prices from {len(all_listings_flat)} listings...")
    
    # Use first query's analysis as reference (for min_realistic, etc.)
    first_query = queries[0] if queries else ""
    first_analysis = query_analyses.get(first_query)
    
    market_prices = calculate_all_market_resale_prices(
        listings=all_listings_flat,
        variant_new_prices=None,
        unrealistic_floor=get_min_realistic_price(first_analysis),
        typical_multiplier=get_auction_multiplier(first_analysis),
        context=context,
        ua=cfg.general.user_agent,
        query_analysis=first_analysis,
    )
    
    market_count = len(market_prices)
    print(f"   ✅ Market prices for {market_count} variants")
    
    # 3b) Web search for NEW prices (one batch!)
    # v9: Pass display_names (readable) instead of hashes
    print(f"\n🌐 Fetching new prices for {len(display_names)} unique products...")
    
    variant_info_map = fetch_variant_info_batch(
        variant_keys=display_names,  # v9: Use readable names!
        car_model=car_model,
        market_prices={key_to_name.get(k, k): v for k, v in market_prices.items()},
        query_analysis=first_analysis,
    )
    
    # v9: Map results back to product_keys for lookup
    variant_info_by_key = {}
    for name, info in variant_info_map.items():
        key = name_to_key.get(name, name)
        variant_info_by_key[key] = info
    variant_info_map = variant_info_by_key
    
    print(f"   ✅ Price info for {len(variant_info_map)} products")
    
    # =========================================================================
    # PHASE 4: EVALUATE ALL LISTINGS
    # =========================================================================
    log_section("v9 PHASE 4: Evaluating All Listings")
    
    for query, listings in all_listings_by_query.items():
        if not listings:
            continue
            
        query_analysis = query_analyses.get(query)
        category = query_categories[query]
        deals_this_query = []
        
        print(f"\n📋 Evaluating {len(listings)} listings for '{query}'")
        
        for listing in listings:
            title = listing.get("title", "")
            variant_key = listing.get("variant_key")
            
            current_price = listing.get("current_price_ricardo")
            buy_now = listing.get("buy_now_price")
            bids_count = listing.get("bids_count")
            hours_remaining = listing.get("hours_remaining")
            
            # Get variant info from global cache
            variant_info = variant_info_map.get(variant_key) if variant_key else None
            
            # v9: Use rule-based bundle detection result
            is_bundle = listing.get("_is_bundle", False)
            products = listing.get("_products", [])
            
            # Create batch_bundle_result from our rule-based detection
            batch_bundle_result = None
            if is_bundle and products:
                batch_bundle_result = {
                    "is_bundle": True,
                    "components": [
                        {"name": p.display_name, "quantity": p.quantity}
                        for p in products
                    ],
                }
            
            # Evaluate
            ai_result = evaluate_listing_with_ai(
                title=title,
                description=listing.get("description") or "",
                current_price=current_price,
                buy_now_price=buy_now,
                image_url=listing.get("image_url"),
                query=query,
                variant_key=variant_key,
                variant_info=variant_info,
                bids_count=bids_count,
                hours_remaining=hours_remaining,
                base_product=query,
                context=context,
                ua=cfg.general.user_agent,
                query_analysis=query_analysis,
                batch_bundle_result=batch_bundle_result,
            )
            
            # Log result
            profit = ai_result.get("expected_profit", 0)
            score = ai_result.get("deal_score", 0)
            strategy = ai_result.get("recommended_strategy", 'skip')
            
            strategy_icon = {'buy_now': '🔥', 'bid_now': '🔥', 'bid': '💰', 'watch': '👀', 'skip': '⏭️'}.get(strategy, '❓')
            print(f"   {strategy_icon} {title[:50]}... | Profit: {profit or 0:.0f} CHF")
            
            # Save to database
            end_time = parse_ricardo_end_time(listing.get("end_time_text"))
            
            if current_price and listing.get("listing_id"):
                record_price_if_changed(conn, listing["listing_id"], current_price, bids_count or 0)
            
            price_source = ai_result.get("price_source", "ai_estimate")
            if ai_result.get("market_based_resale"):
                price_source = ai_result.get("market_source", "auction_demand")
            
            # v9.0: Data sanity validation before DB insert
            # Fix any remaining data inconsistencies
            current_price = listing.get("current_price_ricardo") or listing.get("price")
            predicted = ai_result.get("predicted_final_price")
            resale = ai_result.get("resale_price_est")
            new_price = ai_result.get("new_price")
            
            # Sanity check 1: predicted_final >= current_price
            if predicted and current_price and predicted < current_price:
                predicted = current_price * 1.1
                ai_result["predicted_final_price"] = predicted
            
            # Sanity check 2: resale_price must be <= new_price
            if resale and new_price and resale > new_price:
                resale = new_price * 0.55  # Max 55% of new
                ai_result["resale_price_est"] = resale
            
            # Sanity check 3: If resale exists but new_price is None, estimate new
            if resale and not new_price:
                new_price = resale / 0.40  # Assume 40% resale rate
                ai_result["new_price"] = round(new_price, 2)
            
            data = {
                "platform": "ricardo",
                "listing_id": listing["listing_id"],
                "title": title,
                "description": listing.get("description"),
                "location": listing.get("location"),
                "postal_code": listing.get("postal_code"),
                "shipping": listing.get("shipping"),
                "transport_car": ai_result.get("transport_car"),
                "end_time": end_time,
                "image_url": listing.get("image_url"),
                "url": listing.get("url"),
                "ai_notes": ai_result.get("ai_notes"),
                "buy_now_price": buy_now,
                "current_price_ricardo": current_price,
                "bids_count": bids_count,
                "new_price": ai_result.get("new_price"),
                "resale_price_est": ai_result.get("resale_price_est"),
                "expected_profit": ai_result.get("expected_profit"),
                "deal_score": ai_result.get("deal_score"),
                "variant_key": variant_key,
                "predicted_final_price": ai_result.get("predicted_final_price"),
                "prediction_confidence": ai_result.get("prediction_confidence"),
                "is_bundle": ai_result.get("is_bundle", False),
                "bundle_components": ai_result.get("bundle_components"),
                "resale_price_bundle": ai_result.get("resale_price_bundle"),
                "recommended_strategy": ai_result.get("recommended_strategy"),
                "strategy_reason": ai_result.get("strategy_reason"),
                "market_based_resale": ai_result.get("market_based_resale", False),
                "market_sample_size": ai_result.get("market_sample_size"),
                "market_value": ai_result.get("market_value"),
                "price_source": price_source,
                "buy_now_ceiling": ai_result.get("buy_now_ceiling"),
                "hours_remaining": round(hours_remaining, 1) if hours_remaining is not None else None,
                # v9: Metadata fields
                "web_search_used": variant_info.get("price_source", "").startswith("web") if variant_info else False,
                "cache_hit": variant_info.get("from_cache", False) if variant_info else False,
                "vision_used": ai_result.get("vision_used", False),
                "cleaned_title": listing.get("_cleaned_title"),
            }
            
            upsert_listing(conn, data)
            
            # Collect for detail scraping
            if profit and profit > 0 and listing.get("url"):
                deals_this_query.append({
                    "listing_id": listing["listing_id"],
                    "title": title,
                    "url": listing["url"],
                    "expected_profit": profit,
                    "deal_score": ai_result.get("deal_score"),
                })
        
        all_deals_for_detail.extend(deals_this_query)
    
    print(f"\n✅ v9 Pipeline complete: {total_listings} listings processed")
    return all_deals_for_detail


# ==============================================================================
# DEBUG HELPERS & LOGGING
# ==============================================================================

class TeeOutput:
    """Captures stdout to both console and string buffer."""
    def __init__(self):
        self.terminal = sys.stdout
        self.log = StringIO()
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
    
    def flush(self):
        self.terminal.flush()
    
    def get_log(self):
        return self.log.getvalue()


def log_section(title: str):
    print("\n" + "=" * 90)
    print(f"=== {title}")
    print("=" * 90)


def log_debug(label: str, data: Any):
    print(f"[DEBUG] {label}: {data}")


def save_log_to_file(log_content: str, filename: str = "last_run.log"):
    """Save captured log to file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(log_content)
        print(f"\n📝 Log saved to: {filename}")
    except Exception as e:
        print(f"\n⚠️ Failed to save log: {e}")


def export_listings_to_file(conn, filename: str = "last_run_listings.json"):
    """Export all listings from database to JSON file."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                id, platform, listing_id, title, variant_key, cleaned_title,
                buy_now_price, current_price_ricardo, predicted_final_price,
                new_price, resale_price_est, resale_price_bundle,
                expected_profit, market_value, price_source,
                deal_score, recommended_strategy, strategy_reason,
                market_based_resale, market_sample_size,
                is_bundle, bundle_components,
                bids_count, hours_remaining, end_time,
                location, shipping, pickup_available, seller_rating,
                web_search_used, cache_hit, vision_used,
                created_at, updated_at,
                description, ai_notes, image_url, url
            FROM listings
            ORDER BY expected_profit DESC NULLS LAST
        """)
        
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        
        # Convert to list of dicts
        listings = []
        for row in rows:
            listing = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Convert datetime to string
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                # Convert Decimal to float
                elif hasattr(value, '__float__'):
                    value = float(value)
                listing[col] = value
            listings.append(listing)
        
        # Save to JSON
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                'export_time': datetime.now().isoformat(),
                'total_listings': len(listings),
                'listings': listings
            }, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Exported {len(listings)} listings to: {filename}")
        
        # Also export as CSV for easy analysis
        csv_filename = filename.replace('.json', '.csv')
        with open(csv_filename, 'w', encoding='utf-8', newline='') as f:
            import csv
            writer = csv.DictWriter(f, fieldnames=columns, delimiter=';')
            writer.writeheader()
            writer.writerows(listings)
        print(f"📊 Exported {len(listings)} listings to: {csv_filename}")
        
        # Also create analysis export with quality metrics
        export_analysis_data(listings, "analysis_data.json")
        
    except Exception as e:
        print(f"⚠️ Failed to export listings: {e}")
        traceback.print_exc()


def export_analysis_data(listings: list, filename: str = "analysis_data.json"):
    """
    Export comprehensive analysis data for automatic quality assessment.
    This file contains all data needed for Cascade to analyze run quality.
    """
    from ai_filter import (
        RUN_COST_USD, WEB_SEARCH_COUNT_TODAY, 
        _web_price_cache, _variant_cache
    )
    
    # Calculate quality metrics
    total = len(listings)
    if total == 0:
        return
    
    # Price source breakdown
    price_sources = {}
    for l in listings:
        src = l.get('price_source', 'unknown')
        price_sources[src] = price_sources.get(src, 0) + 1
    
    # Strategy breakdown
    strategies = {}
    for l in listings:
        strat = l.get('recommended_strategy', 'unknown')
        strategies[strat] = strategies.get(strat, 0) + 1
    
    # Profit analysis
    profits = [l.get('expected_profit', 0) or 0 for l in listings]
    profitable = [p for p in profits if p > 20]
    
    # Bundle analysis
    bundles = [l for l in listings if l.get('is_bundle')]
    bundle_issues = []
    for b in bundles:
        comps = b.get('bundle_components', [])
        if isinstance(comps, list):
            for c in comps:
                if isinstance(c, dict) and c.get('new_price_each') == 50.0:
                    bundle_issues.append({
                        'title': b.get('title', '')[:50],
                        'component': c.get('name', ''),
                        'issue': 'Default 50 CHF price used'
                    })
    
    # Suspicious prices (likely wrong)
    suspicious = []
    for l in listings:
        new_p = l.get('new_price', 0) or 0
        resale = l.get('resale_price_est', 0) or 0
        title = l.get('title', '')
        
        # Check for old electronics with too high new_price
        if 'fenix 5' in title.lower() and new_p > 400:
            suspicious.append({'title': title[:50], 'issue': f'Fenix 5 new_price {new_p} CHF too high (model from 2017)'})
        if 'fenix 6' in title.lower() and new_p > 600:
            suspicious.append({'title': title[:50], 'issue': f'Fenix 6 new_price {new_p} CHF too high (model from 2019)'})
        
        # Check for weight equipment with wrong prices
        if any(kw in title.lower() for kw in ['hantelscheiben', 'hantelscheibe', 'gewicht', 'kg']):
            import re
            kg_match = re.search(r'(\d+)\s*kg', title.lower())
            if kg_match:
                kg = float(kg_match.group(1))
                if new_p > 0 and new_p / kg > 10:  # More than 10 CHF/kg is suspicious
                    suspicious.append({'title': title[:50], 'issue': f'{new_p/kg:.1f} CHF/kg is too high for weight plates'})
    
    # v7.3.3: Improved quality score calculation
    # Count web sources (good data quality)
    web_sources = sum(1 for src in price_sources.keys() if src.startswith('web_'))
    web_count = sum(v for k, v in price_sources.items() if k.startswith('web_'))
    market_count = sum(v for k, v in price_sources.items() if 'auction' in k or 'market' in k)
    ai_fallback_count = price_sources.get('ai_estimate', 0)
    unknown_count = price_sources.get('unknown', 0)
    
    # Start with base score
    quality_score = 50.0
    
    # POSITIVE: Web prices found (+2 each, max +30)
    quality_score += min(web_count * 2, 30)
    
    # POSITIVE: Market data used (+3 each, max +15)
    quality_score += min(market_count * 3, 15)
    
    # POSITIVE: Profitable deals found (+1 each, max +15)
    quality_score += min(len(profitable) * 3, 15)
    
    # NEGATIVE: Bundle default prices (-3 each)
    quality_score -= len(bundle_issues) * 3
    
    # NEGATIVE: Suspicious prices (-5 each)
    quality_score -= len(suspicious) * 5
    
    # NEGATIVE: Unknown prices (-2 each)
    quality_score -= unknown_count * 2
    
    quality_score = max(0, min(100, quality_score))
    
    analysis = {
        'export_time': datetime.now().isoformat(),
        'quality_score': round(quality_score, 1),
        'summary': {
            'total_listings': total,
            'profitable_deals': len(profitable),
            'bundles_detected': len(bundles),
            'web_searches_used': WEB_SEARCH_COUNT_TODAY,
            'run_cost_usd': round(RUN_COST_USD, 4),
        },
        'price_sources': price_sources,
        'strategies': strategies,
        'profit_stats': {
            'max': max(profits) if profits else 0,
            'min': min(profits) if profits else 0,
            'avg': sum(profits) / len(profits) if profits else 0,
            'profitable_count': len(profitable),
        },
        'issues': {
            'bundle_default_prices': bundle_issues,
            'suspicious_prices': suspicious,
            'total_issues': len(bundle_issues) + len(suspicious),
        },
        'recommendations': [],
    }
    
    # Add recommendations
    if bundle_issues:
        analysis['recommendations'].append('Bundle pricing needs improvement - using default 50 CHF values')
    if suspicious:
        analysis['recommendations'].append('Some prices appear unrealistic - check AI fallback logic')
    if ai_fallback_count > total * 0.5:
        analysis['recommendations'].append('High AI fallback rate - web search may be failing')
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    
    print(f"📊 Analysis data exported to: {filename} (Quality: {quality_score:.0f}/100)")


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================

def run_once():
    # Start capturing output
    tee = TeeOutput()
    original_stdout = sys.stdout
    sys.stdout = tee
    
    log_section("Starting DealFinder Pipeline v7.2 (Improved Accessory Filter)")

    # --------------------------------------------------------------------------
    # 1) LOAD CONFIG
    # --------------------------------------------------------------------------
    cfg = load_config()
    print_config_summary(cfg)

    reset_run_cost()

    try:
        apply_config(cfg)
    except Exception as e:
        print(f"⚠️ Config apply error: {e}")

    try:
        apply_ai_budget_from_cfg(cfg.ai)
    except Exception as e:
        print(f"⚠️ AI budget load error: {e}")

    max_listings_per_query = getattr(cfg.general, "max_listings_per_query", None)
    car_model = getattr(cfg.general, "car_model", "VW Touran")
    
    # v7.0: Detail scraping settings
    detail_pages_enabled = getattr(cfg.general, "detail_pages_enabled", False)
    max_detail_pages = getattr(cfg.general, "max_detail_pages_per_run", 5)
    
    # v9.0: Clarity detection settings
    clarity_detection_enabled = getattr(cfg.general, "clarity_detection_enabled", True)
    max_unclear_detail_scrapes = getattr(cfg.general, "max_unclear_detail_scrapes", 10)
    max_vision_for_clarity = getattr(cfg.general, "max_vision_for_clarity", 5)
    
    # v9: Always use if available (no config needed - v9 is simply better)
    use_v9_pipeline = V9_AVAILABLE
    
    if use_v9_pipeline:
        print("🚀 v9 Pipeline: Global product deduplication (cost-optimized)")
    else:
        print("⚠️ v9 Pipeline not available - ensure product_extractor.py exists")

    # --------------------------------------------------------------------------
    # 2) DATABASE CONNECTION
    # --------------------------------------------------------------------------
    try:
        conn = get_conn(cfg.pg)
        ensure_schema(conn)
        
        # Clear expired market data
        clear_expired_market_data(conn)
        
        if cfg.general.autoclean_days:
            cleanup_old_listings(conn, cfg.general.autoclean_days)

    except Exception as e:
        print("❌ DB error:", e)
        traceback.print_exc()
        return

    # --------------------------------------------------------------------------
    # 3) CLEAR DB IF TESTING MODE
    # --------------------------------------------------------------------------
    if cfg.db.clear_on_start:
        print("\n⚠️ Testing mode: Clearing all listings...")
        clear_listings(conn)

    # --------------------------------------------------------------------------
    # 4) CLEAR CACHES IF CONFIGURED
    # --------------------------------------------------------------------------
    if cfg.cache.clear_on_start:
        print("\n⚠️ Cache clear mode: Clearing all caches...")
        clear_all_caches()
        clear_query_cache()

    # --------------------------------------------------------------------------
    # 5) ANALYZE QUERIES WITH AI (cached 30 days)
    # --------------------------------------------------------------------------
    queries = cfg.search.get("queries", [])
    
    if not queries:
        print("❌ No search queries configured!")
        return
    
    log_section(f"Analyzing {len(queries)} Search Queries")
    
    query_analyses = analyze_queries(
        queries=queries,
        model=cfg.ai.openai_model,
    )

    # --------------------------------------------------------------------------
    # 6) START BROWSER
    # --------------------------------------------------------------------------
    ensure_chrome_closed()
    tmp_profile = clone_profile()

    # v7.0: Collect all deals for detail scraping at the end
    all_deals_for_detail: List[Dict[str, Any]] = []
    
    # v7.2: Global statistics
    global_stats = {
        "total_scraped": 0,
        "skipped_hardcoded_accessory": 0,
        "skipped_ai_accessory": 0,
        "skipped_defect": 0,
        "skipped_exclude": 0,
        "sent_to_ai": 0,
    }

    try:
        with sync_playwright() as p:
            context = launch_persistent_context(
                p=p,
                profile_dir=tmp_profile,
                headless=False,
                user_agent=cfg.general.user_agent,
            )

            print("🟢 Browser context ready (headful, persistent)")

            # ------------------------------------------------------------------
            # v9 vs v7 PIPELINE BRANCHING
            # ------------------------------------------------------------------
            if use_v9_pipeline:
                # v9: Global product deduplication pipeline
                all_deals_for_detail = run_v9_pipeline(
                    queries=queries,
                    query_analyses=query_analyses,
                    context=context,
                    cfg=cfg,
                    conn=conn,
                    global_stats=global_stats,
                    car_model=car_model,
                    max_listings_per_query=max_listings_per_query,
                )
                
                # Detail scraping for v9
                if detail_pages_enabled and all_deals_for_detail:
                    all_deals_for_detail.sort(key=lambda x: x.get("expected_profit", 0), reverse=True)
                    top_deals = all_deals_for_detail[:max_detail_pages]
                    
                    print(f"\n🔍 v9: Scraping {len(top_deals)} detail pages (top by profit)...")
                    try:
                        from scrapers.detail_scraper import scrape_top_deals
                        enriched_deals = scrape_top_deals(deals=top_deals, context=context, max_pages=len(top_deals))
                        if enriched_deals:
                            for deal in enriched_deals:
                                if deal.get("detail_data"):
                                    detail = deal["detail_data"]
                                    # v9.0: Pass ALL detail data including location
                                    update_listing_details(conn, {
                                        "listing_id": deal["listing_id"],
                                        "seller_rating": detail.get("seller_rating"),
                                        "shipping_cost": detail.get("shipping_cost"),
                                        "pickup_available": detail.get("pickup_available"),
                                        "location": detail.get("location"),
                                        "postal_code": detail.get("postal_code"),
                                        "description": detail.get("full_description"),
                                        "shipping": detail.get("shipping_method"),
                                    })
                        print(f"   ✅ Detail scraping complete")
                    except Exception as e:
                        print(f"   ⚠️ Detail scraping failed: {e}")
            
            # ------------------------------------------------------------------
            # v7 FALLBACK: If v9 not available, show error
            # ------------------------------------------------------------------
            if not use_v9_pipeline:
                print("❌ v9 Pipeline not enabled. Please set pipeline.use_v9_product_extraction: true in config.yaml")
                print("   Or ensure product_extractor.py is available.")
                # Skip to report generation
                pass
            
            # ------------------------------------------------------------------
            # 8) DETAIL SCRAPING SUMMARY
            # ------------------------------------------------------------------
            if detail_pages_enabled and all_deals_for_detail:
                detail_scraped_count = len([d for d in all_deals_for_detail if d.get('detail_scraped')])
                print(f"\n✅ Detail pages scraped: {detail_scraped_count} total (across all queries)")

            # ------------------------------------------------------------------
            # 9) GENERATE REPORT
            # ------------------------------------------------------------------
            try:
                from report_generator import generate_html_report
                report_path = generate_html_report(conn)
                print(f"\n📄 Report generated: {report_path}")
            except ImportError:
                print("\n⚠️ report_generator not available, skipping report")
            except Exception as e:
                print(f"\n⚠️ Report generation failed: {e}")

            # ------------------------------------------------------------------
            # 10) v7.2: GLOBAL STATISTICS
            # ------------------------------------------------------------------
            log_section("v7.2: Pipeline Statistics")
            
            print(f"📊 Total scraped:              {global_stats['total_scraped']}")
            print(f"🎯 Hardcoded accessory filter: {global_stats['skipped_hardcoded_accessory']}")
            print(f"🤖 AI accessory filter:        {global_stats['skipped_ai_accessory']}")
            print(f"🔧 Defect filter:              {global_stats['skipped_defect']}")
            print(f"⚪ Exclude terms filter:       {global_stats['skipped_exclude']}")
            print(f"🧠 Sent to AI evaluation:      {global_stats['sent_to_ai']}")
            
            total_filtered = (
                global_stats['skipped_hardcoded_accessory'] + 
                global_stats['skipped_ai_accessory'] + 
                global_stats['skipped_defect'] + 
                global_stats['skipped_exclude']
            )
            
            if global_stats['total_scraped'] > 0:
                filter_rate = (total_filtered / global_stats['total_scraped']) * 100
                print(f"\n💰 Pre-filter efficiency: {filter_rate:.1f}% filtered (saves AI costs!)")

            # ------------------------------------------------------------------
            # 11) AI COST SUMMARY
            # ------------------------------------------------------------------
            run_cost, day = get_run_cost_summary()
            
            # v7.3.5 FIX: Save day cost BEFORE getting summary!
            # This was missing - day costs were never persisted!
            day_total = save_day_cost()

            log_section("Cost Summary")
            print(f"💰 This run:    ${run_cost:.4f} USD")
            print(f"📊 Today total: ${day_total:.4f} USD")
            print(f"📅 Date:        {day}")
            print(f"🔍 Detail pages scraped: {len([d for d in all_deals_for_detail if d.get('detail_scraped')])} (no AI cost)")

            # ------------------------------------------------------------------
            # 12) EXPORT DATA FOR ANALYSIS
            # ------------------------------------------------------------------
            log_section("Exporting Data for Analysis")
            
            # Export listings to JSON
            export_listings_to_file(conn, "last_run_listings.json")
            
            print("\n✅ Pipeline completed successfully!")

    finally:
        cleanup_profile(tmp_profile)
        
        # Restore stdout and save log
        sys.stdout = original_stdout
        log_content = tee.get_log()
        save_log_to_file(log_content, "last_run.log")


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    try:
        run_once()
    except KeyboardInterrupt:
        print("\n⛔ User cancelled")
    except Exception as e:
        print("\n❌ FATAL ERROR:")
        print(e)
        traceback.print_exc()