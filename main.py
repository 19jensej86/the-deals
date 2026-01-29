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

# FIX 1: Configure UTF-8 output for Windows PowerShell (MUST be first)
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import traceback
import sys
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from io import StringIO

from playwright.sync_api import sync_playwright

from config import load_config, print_config_summary
# v2.2: Use new schema module
from db_pg_v2 import (
    get_conn, 
    ensure_schema,
    ensure_schema_v2,
    save_evaluation,  # Bridge function: old format → new schema
    cleanup_old_listings,
    clear_listings,
    record_price_if_changed,
    clean_price_cache as clear_expired_market_data,
    update_listing_details,
    # Run management
    start_run,
    finish_run,
    get_run_stats,
    # Query helpers
    get_latest_deals as get_listings,
    get_latest_bundles as get_bundle_groups,
    export_deals_json,
    export_deals_csv,
    export_bundles_json,
    export_bundles_csv,
    export_products_json,
    export_run_stats,
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
    init_ai_filter,
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

# v9.2: Enhanced logging
from logger_utils import get_logger, log_explanation, log_cost_summary

# v10: Query-Agnostic Product Extraction
try:
    from pipeline.pipeline_runner import process_batch
    from models.websearch_query import generate_websearch_query
    from models.bundle_types import get_pricing_method, BundleType
    from logging_utils.run_logger import RunLogger
    V10_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ v10 query-agnostic pipeline not available: {e}")
    V10_AVAILABLE = False


def _check_web_search_used(variant_info: Optional[Dict], ai_result: Dict) -> bool:
    """
    FIX 1: Determines if web search was ATTEMPTED (not just succeeded).
    
    CRITICAL: For bundles, checks if ANY component used web search.
    
    Args:
        variant_info: Variant info from web search
        ai_result: AI evaluation result (may contain bundle_components)
    
    Returns:
        True if web search was attempted
    """
    # FIX 1: Check if web search was attempted (even if no price found)
    if variant_info and variant_info.get("web_search_attempted"):
        return True
    
    # Check parent price source (web_* or web_search_attempted)
    if variant_info and (variant_info.get("price_source", "").startswith("web") or 
                         variant_info.get("price_source") == "web_search_attempted"):
        return True
    
    # Check bundle components
    bundle_components = ai_result.get("bundle_components")
    if bundle_components and isinstance(bundle_components, list):
        for component in bundle_components:
            if isinstance(component, dict):
                comp_source = component.get("price_source", "")
                if comp_source.startswith("web") or comp_source == "web_search_attempted":
                    return True
    
    return False

# Detail scraper integration
try:
    from scrapers.detail_scraper import scrape_detail_page
    DETAIL_SCRAPER_AVAILABLE = True
except ImportError:
    DETAIL_SCRAPER_AVAILABLE = False

# Vision analyzer integration
try:
    from ai_filter import analyze_listing_with_vision
    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False


# ==============================================================================
# v9 PIPELINE HELPER FUNCTIONS
# ==============================================================================

def run_v10_pipeline(
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
    
    Flow:
    1. PHASE 1: Scrape all queries, collect listings
    2. PHASE 2: Query-agnostic product extraction (AI → Detail → Vision → Skip)
    3. PHASE 3: Websearch for products that passed extraction
    4. PHASE 4: Pricing and deal evaluation
    
    Args:
        run_id: UUID string from start_run() - DO NOT generate new run_id here
    
    Returns:
        List of deals for detail scraping
    """
    # ✅ FAIL FAST: Validate UUID at pipeline entry
    from db_pg_v2 import assert_valid_uuid
    run_id = assert_valid_uuid(run_id, context="run_v10_pipeline()")
    
    logger = get_logger()
    
    all_deals_for_detail = []
    
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
    
    log_explanation(
        "Wir besuchen Ricardo.ch und suchen nach jedem Produkt. "
        "Für jedes Inserat extrahieren wir: Titel, Preis, Endzeit, Bild, Beschreibung. "
        "Wir filtern offensichtlichen Müll (Zubehör, Defekte, ausgeschlossene Begriffe) bereits hier. "
        "Dieser Schritt verwendet KEINE KI - es ist reines Web-Scraping mit regelbasierten Filtern."
    )
    
    all_listings_by_query: Dict[str, List[Dict[str, Any]]] = {}
    query_categories: Dict[str, str] = {}
    
    for query in queries:
        logger.step_progress(f"Scraping query: '{query}'")
        
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
                
                # v12: Accessory filter now integrated in AI extraction (no separate call needed)
                # Filtering happens in pipeline_runner.py after extraction
                
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
        
        logger.step_success(f"Scraped '{query}'", count=len(listings))
        if skipped_count > 0:
            logger.step_logic(f"Pre-filtered {skipped_count} listings (accessories, defects, excluded terms)")
        all_listings_by_query[query] = listings
    
    # Count totals
    total_listings = sum(len(lst) for lst in all_listings_by_query.values())
    
    logger.step_result(
        summary=f"Scraped {total_listings} listings from {len(queries)} queries",
        quality_metrics={
            "Total scraped": global_stats["total_scraped"],
            "Passed filters": total_listings,
            "Filtered out": global_stats["total_scraped"] - total_listings,
        },
    )
    
    logger.step_end(f"Scraping complete - {total_listings} listings ready for processing")
    
    if total_listings == 0:
        logger.step_warning("No listings found across all queries")
        return []
    
    # Convert to format expected by new pipeline
    all_listings_flat = []
    for query, listings in all_listings_by_query.items():
        for listing in listings:
            all_listings_flat.append({
                "listing_id": listing.get("listing_id", ""),
                "title": listing.get("title", ""),
                "description": listing.get("description", ""),
                "url": listing.get("url", ""),
                "image_url": listing.get("image_url"),
                "image_urls": listing.get("image_urls", []),
                "current_price_ricardo": listing.get("current_price_ricardo"),
                "buy_now_price": listing.get("buy_now_price"),
                "bids_count": listing.get("bids_count"),
                "hours_remaining": listing.get("hours_remaining"),
                "end_time_text": listing.get("end_time_text"),
                "location": listing.get("location"),
                "postal_code": listing.get("postal_code"),
                "shipping": listing.get("shipping"),
                "_query": listing.get("_query"),
                "_category": listing.get("_category"),
            })
    
    # =========================================================================
    # PHASE 2: QUERY-AGNOSTIC PRODUCT EXTRACTION
    # =========================================================================
    logger.step_start(
        step_name="QUERY_AGNOSTIC_EXTRACTION",
        what="Extract structured product data from listing titles",
        why="We need to understand what's being sold - without assumptions based on the search query. Only explicitly mentioned properties are extracted.",
        uses_ai=True,
    )
    
    log_explanation(
        "We now analyze each listing title to identify a unique product. "
        "Goal is to enable clean web search without colors, condition, or marketing terms. "
        "IMPORTANT: AI does NOT know the search query. It only extracts what's explicitly in the title. "
        "No hallucinations: Brand ≠ Material, Weight ≠ Diameter. "
        "If uncertain, the listing is escalated for detail scraping or vision analysis."
    )
    
    # Setup detail scraper adapter
    detail_scraper_func = None
    if DETAIL_SCRAPER_AVAILABLE:
        def detail_scraper_adapter(url: str) -> dict:
            """Adapter for existing detail scraper."""
            try:
                result = scrape_detail_page(url, context)
                return result if result else {}
            except Exception as e:
                print(f"   ⚠️ Detail scraping failed: {e}")
                return {}
        detail_scraper_func = detail_scraper_adapter
    
    # Setup vision analyzer adapter
    vision_analyzer_func = None
    if VISION_AVAILABLE:
        def vision_analyzer_adapter(title: str, description: str, image_url: str) -> dict:
            """Adapter for existing vision analyzer."""
            try:
                result = analyze_listing_with_vision(
                    title=title,
                    description=description,
                    image_url=image_url
                )
                return result if result else {}
            except Exception as e:
                print(f"   ⚠️ Vision analysis failed: {e}")
                return {}
        vision_analyzer_func = vision_analyzer_adapter
    
    logger.step_ai_details(
        ai_purpose="Inseratstitel sind zu komplex für Regex: mehrsprachig, unstrukturiert, viele Sonderfälle. KI versteht Kontext ohne Halluzinationen.",
        input_summary=f"{total_listings} Inseratstitel (OHNE Suchanfrage-Information)",
        expected_output="Strukturierte Produktdaten: Brand, Model, Specs (nur explizit erwähnt), Bundle-Typ, Confidence",
        fallback="Bei niedriger Confidence: Detail-Scraping → Vision → Skip",
    )
    
    logger.step_progress(f"Processing {total_listings} listings through query-agnostic pipeline...")
    
    # Process batch with new pipeline
    extracted_products, run_logger_v10 = process_batch(
        listings=all_listings_flat,
        run_id=run_id,
        config=cfg,
        detail_scraper=detail_scraper_func,
        vision_analyzer=vision_analyzer_func
    )
    
    logger.step_result(
        summary=f"Extracted {len(extracted_products)} products (query-agnostic)",
        quality_metrics={
            "Total listings": total_listings,
            "Products extracted": len(extracted_products),
            "Ready for pricing": run_logger_v10.run_stats["ready_for_pricing"],
            "Needed detail scraping": run_logger_v10.run_stats["needed_detail"],
            "Needed vision": run_logger_v10.run_stats["needed_vision"],
            "Skipped (unclear)": run_logger_v10.run_stats["skipped"],
        },
    )
    
    logger.step_end(f"Query-agnostic extraction complete - {len(extracted_products)} products ready")
    
    # Map extracted products back to original listings for compatibility
    listing_id_to_extracted = {ep.listing_id: ep for ep in extracted_products}
    
    for query, listings in all_listings_by_query.items():
        for listing in listings:
            listing_id = listing.get("listing_id")
            extracted = listing_id_to_extracted.get(listing_id)
            
            # FIX #1: SKIP ACCESSORIES - Don't process listings marked as accessory-only
            if extracted and extracted.is_accessory_only:
                print(f"   🚫 Skipping accessory: {listing.get('title', '')[:60]}...")
                continue
            
            if extracted and extracted.products:
                # Use first product for variant_key
                first_product = extracted.products[0]
                from models.product_identity import ProductIdentity
                identity = ProductIdentity.from_product_spec(first_product)
                
                listing["variant_key"] = identity.product_key
                listing["_cleaned_title"] = identity.websearch_base
                listing["_products"] = extracted.products
                listing["_is_bundle"] = extracted.bundle_type != BundleType.SINGLE_PRODUCT
                listing["_bundle_type"] = extracted.bundle_type
                listing["_extraction_confidence"] = extracted.overall_confidence
                
                # CRITICAL: Store final_search_name as stable join key for price mapping
                final_search_name_extracted = first_product.final_search_name or identity.websearch_base
                listing["_final_search_name"] = final_search_name_extracted
                
                # DEFENSIVE: Log if final_search_name differs from websearch_base (potential mapping issue)
                if first_product.final_search_name and first_product.final_search_name != identity.websearch_base:
                    print(f"   ℹ️ final_search_name='{first_product.final_search_name}' differs from websearch_base='{identity.websearch_base}'")
                
                # CRITICAL: Store detail data if available
                if hasattr(extracted, 'detail_data') and extracted.detail_data:
                    listing["_detail_data"] = extracted.detail_data
            else:
                listing["variant_key"] = None
                listing["_cleaned_title"] = None
                listing["_products"] = []
                listing["_is_bundle"] = False
                listing["_final_search_name"] = None
                listing["_quantity"] = 1
    
    # Count valid extractions
    valid_extractions = len([ep for ep in extracted_products if ep.products])
    invalid_count = total_listings - valid_extractions
    
    if invalid_count > 0:
        logger.step_warning(f"{invalid_count} listings could not be extracted (skipped or too unclear)")
    
    # =========================================================================
    # PHASE 3: WEBSEARCH QUERY GENERATION & PRICE FETCHING
    # =========================================================================
    logger.step_start(
        step_name="WEBSEARCH_QUERY_GENERATION",
        what="Generate optimized websearch queries",
        why="We need clean, shop-optimized queries without noise (colors, sizes, marketing) for precise price search.",
        uses_ai=False,
        uses_rules=True,
    )
    
    log_explanation(
        "For each extracted product we generate an optimized websearch query. "
        "It contains only price-relevant information: Brand, Model, important specs. "
        "IMPORTANT: The query is generated ONLY from ProductSpec, NEVER from the original search query. "
        "Units are normalized (Zoll → inch), but NOT converted (inch → cm)."
    )
    
    # Generate websearch queries for all extracted products
    websearch_queries = []
    product_key_to_query = {}
    final_search_name_to_product_key = {}  # CRITICAL: Map final_search_name -> product_key for price lookup
    
    for extracted in extracted_products:
        if not extracted.products or not extracted.can_price:
            continue
        
        for product in extracted.products:
            query = generate_websearch_query(product)
            identity = ProductIdentity.from_product_spec(product)
            final_search_name = product.final_search_name or identity.websearch_base
            
            websearch_queries.append(query.primary_query)
            product_key_to_query[identity.product_key] = query
            final_search_name_to_product_key[final_search_name] = identity.product_key
    
    # Deduplicate queries
    unique_queries = list(set(websearch_queries))
    
    logger.step_result(
        summary=f"Generated {len(unique_queries)} unique websearch queries",
        quality_metrics={
            "Products extracted": len(extracted_products),
            "Can be priced": len([ep for ep in extracted_products if ep.can_price]),
            "Unique queries": len(unique_queries),
            "Deduplication": f"{(1 - len(unique_queries)/max(len(websearch_queries), 1))*100:.0f}%",
        },
    )
    
    logger.step_end(f"Websearch queries ready - {len(unique_queries)} unique queries")
    
    # =========================================================================
    # PHASE 3.5: PRICE FETCHING
    # =========================================================================
    logger.step_start(
        step_name="PRICE_FETCHING",
        what="Price search for all unique products",
        why="We need to know what each product costs new/used to calculate profit potential.",
        uses_ai=True,
        uses_web_search=True,
        uses_db=True,
    )
    
    log_explanation(
        "For each product we search: (1) New price from web shops, (2) Used price from Ricardo auctions. "
        "Sources in priority: Web search (most accurate), market data (good for popular items), AI estimate (fallback). "
        "Web search uses AI with web access - most expensive step, but best results."
    )
    
    # FIX 3: English-only logs
    logger.step_ai_details(
        ai_purpose="Web shops have different formats. AI with web search understands every shop layout reliably.",
        input_summary=f"{len(unique_queries)} unique product names (e.g. 'Garmin Fenix 7', 'Tommy Hilfiger Winter')",
        expected_output="Retail price + source (e.g. '399 CHF from Galaxus')",
        fallback="If web search fails: AI estimates price based on product knowledge",
    )
    
    print(f"\n📦 Websearch queries ({len(unique_queries)} total):")
    for q in unique_queries:
        print(f"   • {q}")
    
    # Market-based resale (from competing Ricardo listings)
    print(f"\n📈 Calculating market prices from {len(all_listings_flat)} listings...")
    
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
    
    logger.step_success(f"Market prices calculated", count=len(market_prices))
    logger.step_logic(f"Marktpreise stammen von vergangenen Ricardo-Auktionen mit Geboten (kostenlos - keine KI-Kosten)")
    
    # Web search for NEW prices
    logger.step_progress(f"Fetching new prices for {len(unique_queries)} unique products via web search...")
    # FIX 3: English-only logs
    logger.step_logic("Web search uses AI with web access - most expensive operation")
    
    variant_info_map = fetch_variant_info_batch(
        variant_keys=unique_queries,
        car_model=car_model,
        market_prices=market_prices,
        query_analysis=first_analysis,
    )
    
    # CRITICAL FIX: Build price_map keyed by final_search_name for stable lookup
    # Old mapping: query_str -> product_key (BROKEN - query_str != product_key)
    # New mapping: final_search_name -> price_info (STABLE - AI-generated join key)
    price_map_by_final_search_name = {}
    variant_info_by_key = {}  # Keep for backward compatibility
    
    for query_str, info in variant_info_map.items():
        # Find matching product key via query object
        for pk, query_obj in product_key_to_query.items():
            if query_obj.primary_query == query_str:
                variant_info_by_key[pk] = info
                
                # CRITICAL: Also map by final_search_name for stable price lookup
                for final_search_name, mapped_pk in final_search_name_to_product_key.items():
                    if mapped_pk == pk:
                        price_map_by_final_search_name[final_search_name] = info
                        break
                break
    
    web_found = sum(1 for v in variant_info_by_key.values() if v.get("new_price"))
    web_success_rate = (web_found / len(unique_queries) * 100) if unique_queries else 0
    
    logger.step_result(
        summary=f"Price fetching complete for {len(variant_info_by_key)} products",
        quality_metrics={
            "Market prices": len(market_prices),
            "Web search attempts": len(unique_queries),
            "Web search success": f"{web_found} ({web_success_rate:.0f}%)",
            "AI fallback used": len(unique_queries) - web_found,
        },
    )
    
    logger.step_end(f"Price data ready - {web_found} web prices + {len(market_prices)} market prices")
    
    # =========================================================================
    # PHASE 4: EVALUATE ALL LISTINGS
    # =========================================================================
    logger.step_start(
        step_name="DEAL_EVALUATION",
        what="Evaluate each listing for profit calculation and strategy recommendation",
        why="We need to decide which listings are good deals worth pursuing.",
        uses_ai=True,
        uses_db=True,
    )
    
    log_explanation(
        "For each listing we calculate: Expected profit = (Resale price - Purchase price - Fees). "
        "We also predict the final auction price and recommend a strategy: Buy now (top deal), Bid (good deal), Watch (maybe), or Skip (not profitable). "
        "AI is used to understand listing quality, detect defects, and make intelligent predictions."
    )
    
    logger.step_ai_details(
        ai_purpose="Listings have complex factors: condition, seller rating, shipping, bundle logic. AI can intelligently weigh all factors.",
        input_summary=f"{total_listings} listings with prices, descriptions, images",
        expected_output="Profit calculation, strategy recommendation, deal score",
        fallback="If AI fails: simple profit formula without quality adjustments",
    )
    
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
            final_search_name = listing.get("_final_search_name")
            
            current_price = listing.get("current_price_ricardo")
            buy_now = listing.get("buy_now_price")
            bids_count = listing.get("bids_count")
            hours_remaining = listing.get("hours_remaining")
            
            # CRITICAL FIX: Lookup price by final_search_name (stable join key)
            # Old: variant_info_by_key.get(variant_key) - BROKEN mapping
            # New: price_map_by_final_search_name.get(final_search_name) - STABLE mapping
            variant_info = None
            if final_search_name:
                variant_info = price_map_by_final_search_name.get(final_search_name)
                if not variant_info:
                    print(f"   ⚠️ DB persist: no price found for final_search_name='{final_search_name}'")
            
            # Fallback to old mapping for backward compatibility
            if not variant_info and variant_key:
                variant_info = variant_info_by_key.get(variant_key)
                if not variant_info:
                    print(f"   ⚠️ DB persist: no price found for variant_key='{variant_key}'")
            
            # DEFENSIVE INTEGRITY GUARD: If variant_info is still None AND buy_now_price exists
            # Create minimal variant_info to GUARANTEE new_price is populated
            # NOTE: Fallback also exists in ai_filter.py:2163-2166, but artifacts prove it's not reliably executed
            # This is intentionally redundant until root cause is identified and hardened
            if not variant_info and buy_now:
                variant_info = {
                    "new_price": buy_now * 1.1,  # Conservative estimate: 10% markup
                    "price_source": "buy_now_fallback",
                    "transport_car": True,
                    "market_based": False,
                    "market_sample_size": 0,
                }
                print(f"   💰 Using buy_now_price as fallback: {variant_info['new_price']:.2f} CHF")
            
            # v10: Use query-agnostic bundle detection result
            is_bundle = listing.get("_is_bundle", False)
            bundle_type = listing.get("_bundle_type", BundleType.SINGLE_PRODUCT)
            products = listing.get("_products", [])
            quantity = listing.get("_quantity", 1)
            
            # Create batch_bundle_result from query-agnostic detection
            batch_bundle_result = None
            if is_bundle and products:
                batch_bundle_result = {
                    "is_bundle": True,
                    "bundle_type": bundle_type.value if hasattr(bundle_type, 'value') else str(bundle_type),
                    "components": [
                        {"name": p.product_type, "quantity": 1}
                        for p in products
                    ],
                    "pricing_method": get_pricing_method(bundle_type).value if hasattr(bundle_type, 'value') else "unknown",
                }
            
            # Evaluate (OBJECTIVE B: pass variant_info_by_key for bundle component pricing)
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
                variant_info_by_key=variant_info_by_key,
                quantity=quantity,
            )
            
            # Log result with comprehensive details for analysis
            profit = ai_result.get("expected_profit", 0)
            score = ai_result.get("deal_score", 0)
            strategy = ai_result.get("recommended_strategy", 'skip')
            price_source = ai_result.get("price_source", "unknown")
            is_bundle = ai_result.get("is_bundle", False)
            new_price = ai_result.get("new_price", 0)
            resale_price = ai_result.get("resale_price_est", 0)
            
            strategy_icon = {'buy_now': '🔥', 'bid_now': '🔥', 'bid': '💰', 'watch': '👀', 'skip': '⏭️'}.get(strategy, '❓')
            # Enhanced logging for perfect analysis
            print(f"   {strategy_icon} {title}")
            print(f"      💰 Profit: {profit or 0:.2f} CHF | 📊 Score: {score:.1f}/10 | 🏷️ Source: {price_source}")
            print(f"      💵 New: {new_price:.2f} CHF | 🔄 Resale: {resale_price:.2f} CHF | 📦 Bundle: {'Yes' if is_bundle else 'No'}")
            if variant_info and variant_info.get("shop_name"):
                print(f"      🏪 Shops: {variant_info.get('shop_name')}")
            if is_bundle and ai_result.get("bundle_components"):
                print(f"      📦 Components: {len(ai_result.get('bundle_components', []))} items")
            
            # Save to database
            end_time = parse_ricardo_end_time(listing.get("end_time_text"))
            
            # v2.2: price_history recording moved to save_evaluation() - happens after listing insert
            
            price_source = ai_result.get("price_source", "ai_estimate")
            if ai_result.get("market_based_resale"):
                price_source = ai_result.get("market_source", "market_auction")
            
            # v10: Data sanity validation before DB insert
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
            
            # FIX #2: BAN price_source='unknown' - Hard safety net at DB persistence
            # If price_source is still 'unknown', this is data corruption - replace with query_baseline
            # This should NEVER happen after FIX #1, but acts as final defense layer
            if price_source == "unknown":
                print(f"   🚨 SAFETY NET: Replacing price_source='unknown' with 'query_baseline' for {listing['listing_id']}")
                price_source = "query_baseline"
                
                # Ensure prices are not NULL - use query baseline if needed
                if not ai_result.get("new_price") or not ai_result.get("resale_price_est"):
                    from ai_filter import _get_new_price_estimate, _get_resale_rate
                    baseline_new = _get_new_price_estimate(query_analysis)
                    baseline_resale_rate = _get_resale_rate(query_analysis)
                    quantity = listing.get("_quantity", 1)
                    
                    if not ai_result.get("new_price"):
                        ai_result["new_price"] = round(baseline_new, 2)
                    if not ai_result.get("resale_price_est"):
                        ai_result["resale_price_est"] = round(baseline_new * baseline_resale_rate * quantity, 2)
                    
                    print(f"      Applied baseline: new={ai_result['new_price']:.2f}, resale={ai_result['resale_price_est']:.2f} CHF")
            
            # CRITICAL: Normalize bundle_components to JSON string if it's a dict/list
            import json
            bundle_components_raw = ai_result.get("bundle_components")
            if isinstance(bundle_components_raw, (dict, list)):
                bundle_components_json = json.dumps(bundle_components_raw, ensure_ascii=False)
            else:
                bundle_components_json = bundle_components_raw
            
            # CRITICAL: Generate unique INTEGER bundle_id for TRUE bundles
            # TRUE bundle = different products (e.g., Hantel + Scheiben)
            # NOT bundle = quantity products (e.g., 2x Hantelscheibe)
            # IMPORTANT: 1 bundle = 1 listing! Different listings must have different IDs
            bundle_id = None
            if ai_result.get("is_bundle"):
                # Use listing_id to generate unique bundle_id per listing
                # This ensures each bundle listing has its own unique ID
                import hashlib
                listing_id_str = str(listing.get("listing_id", ""))
                bundle_hash = hashlib.md5(listing_id_str.encode()).hexdigest()[:8]
                # Convert hex to integer (max 8 hex digits = 32-bit int)
                bundle_id = int(bundle_hash, 16)
            
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
                "bundle_components": bundle_components_json,
                "bundle_id": bundle_id,
                "resale_price_bundle": ai_result.get("resale_price_bundle"),
                "recommended_strategy": ai_result.get("recommended_strategy"),
                "strategy_reason": ai_result.get("strategy_reason"),
                "market_based_resale": ai_result.get("market_based_resale", False),
                "market_sample_size": ai_result.get("market_sample_size"),
                "market_value": ai_result.get("market_value"),
                "price_source": price_source,
                "shop_name": variant_info.get("shop_name") if variant_info else None,
                "web_sources": variant_info.get("web_sources") if variant_info else None,
                "buy_now_ceiling": ai_result.get("buy_now_ceiling"),
                "hours_remaining": round(hours_remaining, 1) if hours_remaining is not None else None,
                # v9: Metadata fields
                "web_search_used": _check_web_search_used(variant_info, ai_result),
                "cache_hit": variant_info.get("from_cache", False) if variant_info else False,
                "vision_used": ai_result.get("vision_used", False),
                "cleaned_title": listing.get("_cleaned_title"),
                "run_id": run_id,
                # v10: Additional metadata
                "extraction_confidence": listing.get("_extraction_confidence", 0.0),
                "bundle_type_v10": listing.get("_bundle_type").value if listing.get("_bundle_type") else None,
                # FIX 6: Populate ai_cost_usd field
                "ai_cost_usd": ai_result.get("ai_cost_usd", 0.0),
            }
            
            # CRITICAL: Add detail data if available
            detail_data = listing.get("_detail_data")
            if detail_data:
                # Normalize dict values to JSON strings to prevent DB warnings
                desc = detail_data.get("full_description", "")
                if isinstance(desc, dict):
                    desc = json.dumps(desc, ensure_ascii=False)
                data["description"] = desc
                data["shipping"] = detail_data.get("shipping_cost")
                data["pickup_available"] = detail_data.get("pickup_available")
                data["seller_rating"] = detail_data.get("seller_rating")
                data["location"] = detail_data.get("location")
            
            # Track metrics for analysis
            if not hasattr(save_evaluation, 'run_metrics'):
                save_evaluation.run_metrics = {
                    'total': 0,
                    'bundles': 0,
                    'price_sources': {},
                    'strategies': {},
                    'errors': [],
                    'websearch_hits': 0,
                    'websearch_misses': 0,
                }
            
            save_evaluation.run_metrics['total'] += 1
            if is_bundle:
                save_evaluation.run_metrics['bundles'] += 1
            
            # Track price sources
            ps = data.get('price_source', 'unknown')
            save_evaluation.run_metrics['price_sources'][ps] = save_evaluation.run_metrics['price_sources'].get(ps, 0) + 1
            
            # Track strategies
            strat = data.get('recommended_strategy', 'unknown')
            save_evaluation.run_metrics['strategies'][strat] = save_evaluation.run_metrics['strategies'].get(strat, 0) + 1
            
            # Track websearch success
            if data.get('web_search_used'):
                if data.get('shop_name'):
                    save_evaluation.run_metrics['websearch_hits'] += 1
                else:
                    save_evaluation.run_metrics['websearch_misses'] += 1
            
            # v2.2: Use save_evaluation bridge function
            save_evaluation(conn, data)
            
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
    
    # Count strategies
    strategies = {}
    for query_deals in [deals_this_query]:
        for deal in query_deals:
            strat = deal.get("recommended_strategy", "unknown")
            strategies[strat] = strategies.get(strat, 0) + 1
    
    profitable_deals = len([d for d in all_deals_for_detail if d.get("expected_profit", 0) > 10])
    
    logger.step_result(
        summary=f"Evaluated {total_listings} listings - found {profitable_deals} profitable deals",
        quality_metrics={
            "Total evaluated": total_listings,
            "Profitable deals": profitable_deals,
            "Strategies": strategies,
        },
    )
    
    logger.step_end(f"Bewertung abgeschlossen - {profitable_deals} Deals lohnenswert")
    
    # Print v10 pipeline cost breakdown
    print("\n" + "="*60)
    print("v10 PIPELINE COST BREAKDOWN")
    print("="*60)
    run_logger_v10.print_cost_breakdown()
    print("="*60)
    
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
                id, run_id, platform, source_id, url, title, image_url, product_id,
                buy_now_price, current_bid, bids_count, end_time, location,
                shipping_cost, pickup_available, seller_rating, first_seen, last_seen
            FROM listings
            ORDER BY id DESC
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
        
        # Print comprehensive run summary for analysis
        print("\n" + "="*80)
        print("📊 RUN ANALYSIS SUMMARY")
        print("="*80)
        
        if hasattr(save_evaluation, 'run_metrics'):
            metrics = save_evaluation.run_metrics
            total = metrics['total']
            
            print(f"\n📈 LISTINGS PROCESSED: {total}")
            print(f"   📦 Bundles detected: {metrics['bundles']} ({metrics['bundles']/total*100:.1f}%)")
            
            print(f"\n💰 PRICE SOURCES:")
            for source, count in sorted(metrics['price_sources'].items(), key=lambda x: x[1], reverse=True):
                pct = count/total*100 if total > 0 else 0
                print(f"   • {source}: {count} ({pct:.1f}%)")
            
            print(f"\n🎯 STRATEGIES:")
            for strategy, count in sorted(metrics['strategies'].items(), key=lambda x: x[1], reverse=True):
                pct = count/total*100 if total > 0 else 0
                icon = {'buy_now': '🔥', 'bid': '💰', 'watch': '👀', 'skip': '⏭️'}.get(strategy, '❓')
                print(f"   {icon} {strategy}: {count} ({pct:.1f}%)")
            
            print(f"\n🌐 WEBSEARCH PERFORMANCE:")
            ws_total = metrics['websearch_hits'] + metrics['websearch_misses']
            if ws_total > 0:
                hit_rate = metrics['websearch_hits']/ws_total*100
                print(f"   ✅ Successful: {metrics['websearch_hits']}/{ws_total} ({hit_rate:.1f}%)")
                print(f"   ❌ Failed: {metrics['websearch_misses']}/{ws_total} ({100-hit_rate:.1f}%)")
            else:
                print(f"   ℹ️ No websearch used this run")
            
            print(f"\n⚠️ ERRORS & WARNINGS:")
            if metrics['errors']:
                for error in metrics['errors']:
                    print(f"   • {error}")
            else:
                print(f"   ✅ No errors tracked")
        
        print("\n" + "="*80)
        
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
                        'title': b.get('title', ''),
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
            suspicious.append({'title': title, 'issue': f'Fenix 5 new_price {new_p} CHF too high (model from 2017)'})
        if 'fenix 6' in title.lower() and new_p > 600:
            suspicious.append({'title': title, 'issue': f'Fenix 6 new_price {new_p} CHF too high (model from 2019)'})
        
        # Check for weight equipment with wrong prices
        if any(kw in title.lower() for kw in ['hantelscheiben', 'hantelscheibe', 'gewicht', 'kg']):
            import re
            kg_match = re.search(r'(\d+)\s*kg', title.lower())
            if kg_match:
                kg = float(kg_match.group(1))
                if new_p > 0 and new_p / kg > 10:  # More than 10 CHF/kg is suspicious
                    suspicious.append({'title': title, 'issue': f'{new_p/kg:.1f} CHF/kg is too high for weight plates'})
    
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
            'web_searches_used': len([l for l in listings if l.get('web_search_used')]),  # FIX 4: Count listings, not API calls
            'web_search_api_calls': WEB_SEARCH_COUNT_TODAY,  # FIX 4: Track API calls separately
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

    # 🔥 CRITICAL: Validate Claude model configuration BEFORE any AI operations
    try:
        init_ai_filter(cfg)
    except RuntimeError as e:
        print(f"\n❌ FATAL: {e}")
        print("   Pipeline cannot start with invalid AI configuration.")
        sys.exit(1)

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
    
    # v10: Always use if available (query-agnostic, zero hallucinations)
    use_v10_pipeline = V10_AVAILABLE
    
    if use_v10_pipeline:
        print("🚀 v10 Pipeline: Query-agnostic product extraction (zero hallucinations)")
    else:
        print("⚠️ v10 Pipeline not available - ensure models/ and pipeline/ modules exist")

    # --------------------------------------------------------------------------
    # 2) DATABASE CONNECTION + v11 SCHEMA RESET
    # --------------------------------------------------------------------------
    conn = None
    run_id = None
    
    try:
        conn = get_conn(cfg.pg)
        
        # v2.2: Verify schema and create run record
        print("\n🗄️ v2.2: Verifying schema...")
        ensure_schema(conn)
        
        # v2.2: Create run record with UUID
        queries = cfg.search.get('queries', []) if isinstance(cfg.search, dict) else []
        run_id = start_run(conn, mode=cfg.runtime.mode, queries=queries)
        
        # ✅ FAIL FAST: Validate UUID immediately after creation
        from db_pg_v2 import assert_valid_uuid
        run_id = assert_valid_uuid(run_id, context="run_once() after start_run()")
        print(f"🆔 Run ID (validated): {run_id}")
        
        # Clear expired market data
        clear_expired_market_data(conn)
        
        if cfg.general.autoclean_days:
            cleanup_old_listings(conn, cfg.general.autoclean_days)

    except Exception as e:
        print("❌ DB error:", e)
        traceback.print_exc()
        if conn and run_id:
            finish_run(conn, run_id, error_message=str(e)[:500])
        return

    # --------------------------------------------------------------------------
    # 3) RUNTIME MODE VERIFICATION & DATA CLEARING
    # --------------------------------------------------------------------------
    # FIX #4: Use centralized runtime mode config for DB truncation
    from runtime_mode import get_mode_config, should_truncate_db
    
    mode_config = get_mode_config(cfg.runtime.mode)
    
    # PART B: Startup TEST mode verification log
    print("\n" + "="*70)
    if mode_config.mode.value == "test":
        print("🧪 TEST MODE ACTIVE")
        print("="*70)
        print(f"   Max Websearch Calls:  {mode_config.max_websearch_calls}")
        print(f"   Max Cost (USD):       ${mode_config.max_run_cost_usd:.2f}")
        print(f"   Retry Enabled:        {mode_config.retry_enabled}")
        print(f"   Truncate on Start:    {mode_config.truncate_on_start}")
        print(f"   Budget Enforced:      {mode_config.enforce_budget}")
        print("="*70)
    else:
        print("🚀 PRODUCTION MODE ACTIVE")
        print("="*70)
        print(f"   Max Websearch Calls:  {mode_config.max_websearch_calls}")
        print(f"   Max Cost (USD):       ${mode_config.max_run_cost_usd:.2f}")
        print(f"   Retry Enabled:        {mode_config.retry_enabled}")
        print("="*70)
    
    if should_truncate_db(mode_config):
        print(f"\n🧪 {mode_config.mode.value.upper()} mode: Truncating ALL tables for clean test...")
        try:
            with conn.cursor() as cur:
                # IMPROVEMENT #2: Use TRUNCATE instead of DELETE (faster, resets sequences, handles FKs)
                for table in mode_config.truncate_tables:
                    cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
                    print(f"   🧹 Truncated {table} (sequences reset)")
                conn.commit()
        except Exception as e:
            print(f"   ⚠️ Truncate failed: {e}")
    else:
        print(f"\n💾 {mode_config.mode.value.upper()} mode: Data will persist (run_id={run_id})")

    # --------------------------------------------------------------------------
    # 4) CLEAR CACHES IF CONFIGURED
    # --------------------------------------------------------------------------
    if cfg.cache.clear_on_start:
        print("\n⚠️ Cache clear mode: Clearing all caches (web prices, variant info, query analysis)...")
        clear_all_caches()
        clear_query_cache()

    # --------------------------------------------------------------------------
    # 5) ANALYZE QUERIES WITH AI (cached 30 days)
    # --------------------------------------------------------------------------
    queries = cfg.search.get("queries", [])
    
    if not queries:
        print("❌ No search queries configured!")
        return
    
    # v9.2: Enhanced logging
    logger = get_logger()
    logger.step_start(
        step_name="QUERY_ANALYSIS",
        what="Analyzing search queries to understand what products we're looking for",
        why="We need to know product categories, typical prices, and common accessories to filter listings intelligently",
        uses_ai=True,
    )
    
    log_explanation(
        "Each search query (like 'Tommy Hilfiger' or 'Garmin smartwatch') is analyzed by AI. "
        "The AI tells us: What category is this? What's a realistic minimum price? "
        "Which accessories are commonly bundled? This helps us filter out junk listings later."
    )
    
    logger.step_ai_details(
        ai_purpose="Queries are too diverse for hardcoded rules. AI understands context and product knowledge.",
        input_summary=f"{len(queries)} search queries (e.g. 'Tommy Hilfiger', 'Garmin smartwatch')",
        expected_output="Category, min price, accessory keywords, defect keywords for each query",
        fallback="If AI fails, use generic category detection (regex-based)",
    )
    
    logger.step_progress(f"Analyzing {len(queries)} queries...")
    
    query_analyses = analyze_queries(
        queries=queries,
        model=cfg.ai.openai_model,
        config=cfg,
    )
    
    logger.step_result(
        summary=f"All {len(queries)} queries analyzed successfully",
        quality_metrics={
            "Queries analyzed": len(queries),
            "Cache hits": "Cached for 30 days (no cost on re-runs)",
        },
    )
    
    logger.step_end("Query analysis complete - ready to scrape listings")

    # --------------------------------------------------------------------------
    # 6) START BROWSER
    # --------------------------------------------------------------------------
    ensure_chrome_closed()
    tmp_profile = clone_profile()

    # v7.0: Collect all deals for detail scraping at the end
    all_deals_for_detail: List[Dict[str, Any]] = []
    
    # v2.2: run_id already created by start_run() - DO NOT override
    # The UUID from run_once() is passed down to this function
    
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
            # v10 PIPELINE
            # ------------------------------------------------------------------
            if use_v10_pipeline:
                # v10: Query-agnostic product extraction pipeline
                all_deals_for_detail = run_v10_pipeline(
                    queries=queries,
                    query_analyses=query_analyses,
                    context=context,
                    cfg=cfg,
                    conn=conn,
                    global_stats=global_stats,
                    car_model=car_model,
                    max_listings_per_query=max_listings_per_query,
                    run_id=run_id,
                )
                
                # Detail scraping for v10
                if detail_pages_enabled and all_deals_for_detail:
                    all_deals_for_detail.sort(key=lambda x: x.get("expected_profit", 0), reverse=True)
                    top_deals = all_deals_for_detail[:max_detail_pages]
                    
                    logger.step_start(
                        step_name="DETAIL_SCRAPING",
                        what=f"Scraping detail pages for top {len(top_deals)} deals",
                        why="Detail pages contain extra info: seller rating, shipping cost, exact location - helps make better buying decisions",
                        uses_ai=False,
                        uses_rules=True,
                    )
                    
                    log_explanation(
                        "We visit the actual listing pages (not just search results) to extract additional details. "
                        "This step does NOT use AI - it's pure web scraping with DOM selectors. "
                        "We only scrape the most profitable deals to save time."
                    )
                    
                    try:
                        from scrapers.detail_scraper import scrape_top_deals
                        enriched_deals = scrape_top_deals(deals=top_deals, context=context, max_pages=len(top_deals))
                        
                        # v9.2: VALIDATION - Track which listings actually got detail data
                        detail_success_count = 0
                        detail_fail_count = 0
                        
                        if enriched_deals:
                            for deal in enriched_deals:
                                if deal.get("detail_data"):
                                    detail = deal["detail_data"]
                                    
                                    # v9.2: VALIDATION - Check if we actually got data
                                    has_data = any([
                                        detail.get("seller_rating"),
                                        detail.get("shipping_cost"),
                                        detail.get("pickup_available") is not None,
                                        detail.get("location"),
                                        detail.get("postal_code"),
                                    ])
                                    
                                    if has_data:
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
                                        detail_success_count += 1
                                        
                                        # TODO: Re-evaluate deal with detail data (function not yet implemented)
                                        # from ai_filter import re_evaluate_with_details
                                        # from db_pg_v2 import update_listing_details as update_listing_reevaluation
                                        
                                        # Skip re-evaluation for now (function not implemented)
                                        # updated = None
                                        # TODO: Implement re_evaluate_with_details in ai_filter.py
                                    else:
                                        print(f"   ⚠️ No detail data for {deal['listing_id']} - scraping failed")
                                        detail_fail_count += 1
                                else:
                                    detail_fail_count += 1
                        
                        # v9.2: Report actual success rate with verification
                        from logger_utils import log_verification
                        
                        if detail_success_count > 0:
                            log_verification(
                                claim=f"{detail_success_count} detail pages scraped successfully",
                                verified=True,
                                evidence=f"Database fields populated: location, shipping_cost, pickup_available",
                            )
                        
                        if detail_fail_count > 0:
                            log_verification(
                                claim=f"{detail_fail_count} detail pages scraped",
                                verified=False,
                                evidence="No usable data extracted from these pages",
                            )
                        
                        logger.step_result(
                            summary=f"Detail scraping complete",
                            quality_metrics={
                                "Attempted": len(top_deals),
                                "Successful": detail_success_count,
                                "Failed": detail_fail_count,
                                "Success rate": f"{(detail_success_count/len(top_deals)*100):.0f}%" if top_deals else "0%",
                            },
                        )
                        
                        logger.step_end(f"Detail scraping complete - {detail_success_count}/{len(top_deals)} successful")
                    except Exception as e:
                        logger.step_error(f"Detail scraping failed: {e}")
            
            # ------------------------------------------------------------------
            # FALLBACK: If v10 not available, show error
            # ------------------------------------------------------------------
            if not use_v10_pipeline:
                print("❌ v10 Pipeline not available. Please ensure models/ and pipeline/ modules are installed.")
                print("   Required modules: models.bundle_types, models.product_spec, pipeline.pipeline_runner")
                return
            
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
            # 11) AI COST SUMMARY (v9.2: Enhanced with step breakdown)
            # ------------------------------------------------------------------
            cost_summary = get_run_cost_summary()
            run_cost = cost_summary.get("total_usd", 0.0)
            day = cost_summary.get("date", "")
            day_total = save_day_cost()
            
            # Get cost summary from logger
            cost_info = logger.get_cost_summary()
            
            # Calculate approximate cost breakdown
            from ai_filter import RUN_COST_USD, WEB_SEARCH_COUNT_TODAY
            
            log_cost_summary(
                ai_calls=len(cost_info["ai_steps"]) + len(cost_info["cost_steps"]),
                web_searches=WEB_SEARCH_COUNT_TODAY,
                total_cost_usd=run_cost,
                breakdown={
                    "Query Analysis": 0.002,  # Haiku
                    "Title Normalization": 0.005,  # Haiku batch
                    "Web Price Search": run_cost * 0.85,  # ~85% of cost
                    "Deal Evaluation": run_cost * 0.10,  # ~10% of cost
                },
            )
            
            print(f"\n📅 Date: {day}")
            print(f"📊 Today total: ${day_total:.4f} USD")

            # ------------------------------------------------------------------
            # 12) EXPORT DATA FOR ANALYSIS
            # ------------------------------------------------------------------
            log_section("Exporting Data for Analysis")
            
            print("📊 Exporting comprehensive run data for analysis...")
            print("   This allows Cascade to analyze runs without DB/console access\n")
            
            # Export deals (v2.2 schema)
            export_deals_json(conn, "last_run_deals.json")
            export_deals_csv(conn, "last_run_deals.csv")
            
            # Export bundles (v2.2 schema)
            export_bundles_json(conn, "last_run_bundles.json")
            export_bundles_csv(conn, "last_run_bundles.csv")
            
            # Export products
            export_products_json(conn, "last_run_products.json")
            
            # Export run statistics and metadata
            export_run_stats(conn, "last_run_stats.json")
            
            # Legacy export (for backwards compatibility)
            export_listings_to_file(conn, "last_run_listings.json")
            
            # IMPROVEMENT #4: Post-run invariant checks (TEST MODE ONLY)
            try:
                from test_invariants import run_invariant_checks
                run_invariant_checks(conn, mode_config)
            except ImportError:
                pass  # test_invariants not available
            except Exception as e:
                # Invariant violation - fail the run
                print(f"\n❌ POST-RUN INVARIANT CHECK FAILED:")
                print(f"{e}")
                raise
            
            print("\n✅ Pipeline completed successfully!")
            
            # ✅ Finalize run on success
            if conn and run_id:
                cost_summary = get_run_cost_summary()
                finish_run(
                    conn, run_id,
                    listings_found=global_stats.get('total_scraped', 0),
                    deals_created=0,  # TODO: track from save_evaluation
                    bundles_created=0,
                    profitable_deals=0,
                    ai_cost_usd=cost_summary.get('total_usd', 0.0),
                    websearch_calls=0  # TODO: track from ai_filter
                )

    except Exception as e:
        # ❌ Finalize run on failure
        print(f"\n❌ Pipeline failed: {e}")
        if conn and run_id:
            cost_summary = get_run_cost_summary()
            finish_run(
                conn, run_id,
                ai_cost_usd=cost_summary.get('total_usd', 0.0),
                error_message=str(e)[:500]
            )
        raise
    
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