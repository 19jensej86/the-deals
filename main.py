"""
DealFinder Main Pipeline - v7.1 (Accessory Filter Fix)
======================================================
Changes from v7.0:
- FIX: Added accessory keyword filtering (was missing!)
- Accessories like armbands, cases, chargers are now filtered out
- Uses AI-generated accessory_keywords from query_analyzer

Pipeline Steps:
1. Load config
2. Connect to database (auto-migrate schema)
3. Optionally clear DB (testing mode)
4. Analyze all queries with AI (cached 30 days)
5. Start browser
6. For each query:
   a. Scrape Ricardo SERP
   b. Filter: exclude terms, defects, AND accessories (v7.1!)
   c. Cluster listings into variants
   d. Calculate market resale from auctions with bids
   e. Fetch variant info (new prices, transport)
   f. Evaluate each listing (with global sanity checks!)
   g. Save to database
7. Scrape detail pages for top deals
8. Generate HTML report
9. Show AI cost summary
"""

import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

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
from utils_text import contains_excluded_terms, normalize_whitespace

from query_analyzer import (
    analyze_queries,
    clear_query_cache,
    get_min_realistic_price,
    get_auction_multiplier,
    get_defect_keywords,
    get_accessory_keywords,  # v7.1: Added for accessory filtering!
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
# DEBUG HELPERS
# ==============================================================================

def log_section(title: str):
    print("\n" + "=" * 90)
    print(f"=== {title}")
    print("=" * 90)


def log_debug(label: str, data: Any):
    print(f"[DEBUG] {label}: {data}")


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================

def run_once():
    log_section("Starting DealFinder Pipeline v7.1 (Accessory Filter Fix)")

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
                if query_analysis:
                    print(f"📊 Category: {query_analysis.get('category')}")
                    print(f"📊 Reference price: ~{query_analysis.get('new_price_estimate', 'N/A')} CHF")
                    print(f"📊 Resale rate: {query_analysis.get('resale_rate', 0.4)*100:.0f}% (fallback)")
                    print(f"📊 Min realistic: {query_analysis.get('min_realistic_price', 10)} CHF")
                    
                    # v7.1: Show filter keywords
                    defect_kw = get_defect_keywords(query_analysis)
                    accessory_kw = get_accessory_keywords(query_analysis)
                    if defect_kw:
                        print(f"📊 Defect keywords: {defect_kw[:5]}{'...' if len(defect_kw) > 5 else ''}")
                    if accessory_kw:
                        print(f"📊 Accessory keywords: {accessory_kw[:5]}{'...' if len(accessory_kw) > 5 else ''}")
                
                processed_for_query = 0
                skipped_accessories = 0
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
                        title = listing.get("title") or ""
                        normalized_title = normalize_whitespace(title)
                        title_lower = normalized_title.lower()

                        # Skip excluded terms (from config)
                        if contains_excluded_terms(title_lower, cfg.general.exclude_terms):
                            print(f"⚪ Skip (exclude): {title[:50]}")
                            continue

                        # Skip defect keywords from query analysis
                        defect_kw = get_defect_keywords(query_analysis)
                        if defect_kw and contains_excluded_terms(title_lower, defect_kw):
                            print(f"⚪ Skip (defect): {title[:50]}")
                            skipped_defects += 1
                            continue

                        # v7.1 FIX: Skip accessory keywords from query analysis!
                        accessory_kw = get_accessory_keywords(query_analysis)
                        if accessory_kw and contains_excluded_terms(title_lower, accessory_kw):
                            print(f"⚪ Skip (accessory): {title[:50]}")
                            skipped_accessories += 1
                            continue

                        all_listings.append(listing)
                        all_titles.append(title)

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

                # v7.1: Show filter stats
                print(f"\n📦 Found {len(all_listings)} listings to process")
                if skipped_defects > 0:
                    print(f"   🗑️ Filtered {skipped_defects} defect listings")
                if skipped_accessories > 0:
                    print(f"   🗑️ Filtered {skipped_accessories} accessory listings")

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
            # 10) AI COST SUMMARY
            # ------------------------------------------------------------------
            run_cost, day = get_run_cost_summary()
            day_total = get_day_cost_summary()

            log_section("Cost Summary")
            print(f"💰 This run:    ${run_cost:.4f} USD")
            print(f"📊 Today total: ${day_total:.4f} USD")
            print(f"📅 Date:        {day}")
            print(f"🔍 Detail pages scraped: {len([d for d in all_deals_for_detail if d.get('detail_scraped')])} (no AI cost)")

    finally:
        cleanup_profile(tmp_profile)


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