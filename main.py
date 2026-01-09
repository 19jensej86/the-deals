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
    is_accessory_title,      # v7.2: Now query/category-aware!
    is_defect_title,         # v7.2: For hardcoded defect check
    detect_category,         # v7.2: Auto-detect category from query
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
    clear_all_caches,
    cluster_variants_from_titles,
    get_variant_for_title,
    calculate_all_market_resale_prices,
    fetch_variant_info_batch,
    evaluate_listing_with_ai,
    to_float,
)


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
                id, platform, listing_id, title, description,
                location, postal_code, shipping, transport_car,
                end_time, image_url, url, detected_product,
                ai_notes, buy_now_price, current_price_ricardo,
                bids_count, new_price, resale_price_est,
                expected_profit, deal_score, created_at, updated_at,
                variant_key, predicted_final_price, prediction_confidence,
                is_bundle, bundle_components, resale_price_bundle,
                recommended_strategy, strategy_reason,
                market_based_resale, market_sample_size,
                market_value, price_source, buy_now_ceiling,
                hours_remaining, seller_rating, shipping_cost,
                pickup_available
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
        cur.close()
        
    except Exception as e:
        print(f"⚠️ Failed to export listings: {e}")
        traceback.print_exc()


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
            # 7) FOR EACH QUERY
            # ------------------------------------------------------------------
            for query in queries:
                log_section(f"Search: {query}")
                
                query_analysis = query_analyses.get(query)
                
                # v7.2: Get category (from AI analysis or auto-detect)
                if query_analysis:
                    category = get_category(query_analysis)
                else:
                    category = detect_category(query)
                
                if query_analysis:
                    print(f"📊 Category: {category}")
                    print(f"📊 Reference price: ~{query_analysis.get('new_price_estimate', 'N/A')} CHF")
                    print(f"📊 Resale rate: {query_analysis.get('resale_rate', 0.4)*100:.0f}% (fallback)")
                    print(f"📊 Min realistic: {query_analysis.get('min_realistic_price', 10)} CHF")
                    
                    # v7.2: Show both filter keyword sources
                    defect_kw = get_defect_keywords(query_analysis)
                    ai_accessory_kw = get_accessory_keywords(query_analysis)
                    
                    if defect_kw:
                        print(f"📊 Defect keywords (AI): {defect_kw[:5]}{'...' if len(defect_kw) > 5 else ''}")
                    if ai_accessory_kw:
                        print(f"📊 Accessory keywords (AI): {ai_accessory_kw[:5]}{'...' if len(ai_accessory_kw) > 5 else ''}")
                    
                    print(f"📊 Hardcoded accessory filter: ENABLED (query-aware, category={category})")
                
                processed_for_query = 0
                skipped_hardcoded_acc = 0
                skipped_ai_acc = 0
                skipped_defects = 0
                all_listings = []
                all_titles = []

                # --------------------------------------------------------------
                # 7a) SCRAPE RICARDO SERP
                # --------------------------------------------------------------
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

                        # PRE-FILTER 0: Skip excluded terms (from config)
                        if contains_excluded_terms(title_lower, cfg.general.exclude_terms):
                            print(f"⚪ Skip (exclude): {title[:50]}")
                            global_stats["skipped_exclude"] += 1
                            continue

                        # ------------------------------------------------------
                        # v7.2 PRE-FILTER 1: HARDCODED accessory detection
                        # This catches things AI might miss (armband, silikon, etc.)
                        # Query-aware: won't filter if user searches FOR accessories
                        # Category-aware: fitness "set" = bundle, not accessory!
                        # ------------------------------------------------------
                        if is_accessory_title(normalized_title, query=query, category=category):
                            print(f"🎯 Skip (hardcoded accessory): {title[:50]}")
                            skipped_hardcoded_acc += 1
                            global_stats["skipped_hardcoded_accessory"] += 1
                            continue

                        # ------------------------------------------------------
                        # PRE-FILTER 2: AI-generated accessory keywords
                        # This catches product-specific accessories AI identified
                        # v7.2 FIX: Category-aware - don't filter fitness bundles!
                        # ------------------------------------------------------
                        ai_accessory_kw = get_accessory_keywords(query_analysis)
                        if ai_accessory_kw:
                            # Filter out bundle keywords for fitness category
                            if category.lower() in ["fitness", "sport"]:
                                # Don't filter "set", "stange", "scheibe" for fitness
                                ai_accessory_kw = [kw for kw in ai_accessory_kw 
                                                   if kw.lower() not in ["set", "stange", "scheibe", "halterung"]]
                            
                            if ai_accessory_kw and contains_excluded_terms(title_lower, ai_accessory_kw):
                                print(f"🤖 Skip (AI accessory): {title[:50]}")
                                skipped_ai_acc += 1
                                global_stats["skipped_ai_accessory"] += 1
                                continue

                        # ------------------------------------------------------
                        # PRE-FILTER 3: Defect keywords
                        # ------------------------------------------------------
                        defect_kw = get_defect_keywords(query_analysis)
                        if defect_kw and contains_excluded_terms(title_lower, defect_kw):
                            print(f"🔧 Skip (defect): {title[:50]}")
                            skipped_defects += 1
                            global_stats["skipped_defect"] += 1
                            continue

                        all_listings.append(listing)
                        all_titles.append(title)
                        global_stats["sent_to_ai"] += 1

                        # Limit check
                        if max_listings_per_query and len(all_listings) >= max_listings_per_query:
                            print(f"🛑 Reached limit ({max_listings_per_query}) for '{query}'")
                            break

                except Exception as e:
                    print(f"❌ Scraping error: {e}")
                    traceback.print_exc()
                    continue

                if not all_listings:
                    print(f"⚠️ No listings found for '{query}'")
                    continue

                # v7.2: Show filter stats per query
                print(f"\n📦 Found {len(all_listings)} listings to process")
                if skipped_hardcoded_acc > 0:
                    print(f"   🎯 Filtered {skipped_hardcoded_acc} by hardcoded accessory detection")
                if skipped_ai_acc > 0:
                    print(f"   🤖 Filtered {skipped_ai_acc} by AI accessory keywords")
                if skipped_defects > 0:
                    print(f"   🔧 Filtered {skipped_defects} defect listings")

                # --------------------------------------------------------------
                # 7b) CLUSTER INTO VARIANTS
                # --------------------------------------------------------------
                log_section(f"Clustering {len(all_titles)} Titles")
                
                cluster_result = cluster_variants_from_titles(
                    titles=all_titles,
                    base_product=query,
                    query_analysis=query_analysis,
                )

                # Assign variant keys to listings
                for listing in all_listings:
                    title = listing.get("title", "")
                    variant_key = get_variant_for_title(title, cluster_result, query)
                    listing["variant_key"] = variant_key

                # --------------------------------------------------------------
                # 7c) v6.3: CALCULATE MARKET RESALE (with sanity checks!)
                # --------------------------------------------------------------
                log_section("v6.3: Market Price Calculation (with Sanity Checks)")
                
                # Get unique variant keys
                variant_keys = list(set(
                    l.get("variant_key") for l in all_listings 
                    if l.get("variant_key")
                ))
                
                min_realistic = get_min_realistic_price(query_analysis)
                auction_multiplier = get_auction_multiplier(query_analysis)
                
                market_prices = calculate_all_market_resale_prices(
                    listings=all_listings,
                    variant_new_prices=None,
                    unrealistic_floor=min_realistic,
                    typical_multiplier=auction_multiplier,
                    context=context,
                    ua=cfg.general.user_agent,
                    query_analysis=query_analysis,
                )
                
                if market_prices:
                    print(f"\n✅ Market prices calculated for {len(market_prices)} variants")
                    
                    # Clear stale market data for variants we just recalculated
                    for vk in market_prices.keys():
                        clear_stale_market_for_variant(conn, vk)
                else:
                    print(f"\n⚠️ No market prices could be calculated (not enough auction data)")

                # --------------------------------------------------------------
                # 7d) FETCH VARIANT INFO (NEW PRICES, TRANSPORT)
                # --------------------------------------------------------------
                log_section(f"Fetching Info for {len(variant_keys)} Variants")
                
                variant_info_map = fetch_variant_info_batch(
                    variant_keys=variant_keys,
                    car_model=car_model,
                    market_prices=market_prices,
                    query_analysis=query_analysis,
                )

                # --------------------------------------------------------------
                # 7e) EVALUATE EACH LISTING (v6.3: with global sanity checks!)
                # --------------------------------------------------------------
                log_section(f"Evaluating {len(all_listings)} Listings")

                for listing in all_listings:
                    title = listing.get("title", "")
                    variant_key = listing.get("variant_key")
                    
                    current_price = listing.get("current_price_ricardo")
                    buy_now = listing.get("buy_now_price")
                    bids_count = listing.get("bids_count")
                    hours_remaining = listing.get("hours_remaining")
                    
                    print(f"\n🔍 Evaluating: {title[:60]}...")
                    if variant_key:
                        print(f"   Variant: {variant_key}")
                    
                    # Get variant info
                    variant_info = variant_info_map.get(variant_key) if variant_key else None

                    # Evaluate (v6.3: includes global sanity checks!)
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
                    )

                    processed_for_query += 1

                    # Log result
                    if not ai_result.get("is_relevant", True):
                        print(f"   ⚠️ Irrelevant: {ai_result.get('ai_notes', '')[:50]}")
                    else:
                        profit = ai_result.get("expected_profit")
                        score = ai_result.get("deal_score", 0)
                        strategy = ai_result.get("recommended_strategy", 'unknown')
                        market_based = ai_result.get("market_based_resale")
                        price_source = ai_result.get("price_source", "unknown")
                        
                        strategy_icon = {
                            'buy_now': '🔥',
                            'bid_now': '🔥',
                            'bid': '💰',
                            'watch': '👀',
                            'skip': '⏭️',
                        }.get(strategy, '❓')
                        
                        if market_based:
                            source_text = f"📈 Market ({price_source})"
                        else:
                            source_text = "🤖 AI"
                        
                        print(f"   {strategy_icon} {strategy.upper()} | "
                              f"Profit: {profit or 0:.0f} CHF | "
                              f"Score: {score:.1f} | "
                              f"{source_text}")

                    # ----------------------------------------------------------
                    # 7f) SAVE TO DATABASE
                    # ----------------------------------------------------------
                    end_time = parse_ricardo_end_time(listing.get("end_time_text"))
                    
                    if end_time is None and current_price is not None and buy_now is None:
                        print(f"   ⚠️ Could not parse end_time: '{listing.get('end_time_text')}'")

                    # Record price history if auction
                    if current_price and listing.get("listing_id"):
                        record_price_if_changed(
                            conn, 
                            listing["listing_id"], 
                            current_price, 
                            bids_count or 0
                        )

                    price_source = ai_result.get("price_source", "ai_estimate")
                    if ai_result.get("market_based_resale"):
                        price_source = ai_result.get("market_source", "auction_demand")

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
                        "detected_product": query,
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
                    }

                    upsert_listing(conn, data)
                    
                    # v7.0: Collect for detail scraping
                    # Only collect if has profit and URL
                    if ai_result.get("expected_profit") and listing.get("url"):
                        all_deals_for_detail.append({
                            "listing_id": listing["listing_id"],
                            "title": title,
                            "url": listing["url"],
                            "expected_profit": ai_result.get("expected_profit"),
                            "deal_score": ai_result.get("deal_score"),
                        })

                print(f"\n✅ Processed {processed_for_query} listings for '{query}'")

            # ------------------------------------------------------------------
            # 8) v7.0: DETAIL PAGE SCRAPING
            # ------------------------------------------------------------------
            if detail_pages_enabled and all_deals_for_detail:
                log_section(f"v7.0: Detail Page Scraping (Top {max_detail_pages} Deals)")
                
                try:
                    from scrapers.detail_scraper import scrape_top_deals
                    
                    # Scrape detail pages for top deals
                    enriched_deals = scrape_top_deals(
                        deals=all_deals_for_detail,
                        context=context,
                        max_pages=max_detail_pages,
                    )
                    
                    # Update database with detail data
                    for deal in enriched_deals:
                        if deal.get("detail_scraped"):
                            update_listing_details(conn, deal)
                    
                except ImportError as e:
                    print(f"⚠️ Detail scraper not available: {e}")
                except Exception as e:
                    print(f"⚠️ Detail scraping failed: {e}")
                    traceback.print_exc()
            
            elif detail_pages_enabled:
                print("\n⚠️ No deals with profit found for detail scraping")

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
            day_total = get_day_cost_summary()

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