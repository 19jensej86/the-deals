"""
Pipeline Runner - Main Processing Flow
=======================================
Orchestrates the complete extraction → pricing → evaluation flow.

CRITICAL: Query-agnostic, transparent escalation, cost tracking.
"""

from typing import List, Dict, Any, Optional
from models.extracted_product import ExtractedProduct
from extraction.ai_extractor import extract_product_with_ai
from pipeline.decision_gates import decide_next_step, should_skip
from logging_utils.listing_logger import ListingProcessingLog
from logging_utils.run_logger import RunLogger


def process_listing(
    listing: Dict[str, Any],
    run_logger: RunLogger,
    detail_scraper=None,
    vision_analyzer=None
) -> Optional[ExtractedProduct]:
    """
    Process a single listing through the pipeline.
    
    Flow:
    1. AI Extraction (initial)
    2. Decision Gate 1 → pricing or detail
    3. Detail Scraping (if needed)
    4. Decision Gate 2 → pricing or vision
    5. Vision Analysis (if needed)
    6. Decision Gate 3 → pricing or skip
    
    Args:
        listing: Raw listing data
        run_logger: Run-level logger
        detail_scraper: Optional detail scraper function
        vision_analyzer: Optional vision analyzer function
    
    Returns:
        ExtractedProduct or None if skipped
    """
    
    listing_id = listing.get("listing_id", "unknown")
    title = listing.get("title", "")
    description = listing.get("description", "")
    
    # Get listing-specific logger
    log = run_logger.get_listing_log(listing_id)
    
    # === PHASE 1: AI EXTRACTION (INITIAL) ===
    log.log_step("ai_extraction_initial", title=title[:50])
    
    extracted = extract_product_with_ai(
        listing_id=listing_id,
        title=title,
        description=description
    )
    
    # Log AI cost
    log.log_ai_call(
        purpose="initial_extraction",
        model="claude-3-5-haiku-20241022",
        cost_usd=extracted.ai_cost_usd
    )
    
    # OBSERVABILITY: Log extracted ProductSpec for debugging
    if extracted.products:
        spec = extracted.products[0]
        print(f"   🧠 Extracted ProductSpec:")
        print(f"      product_type: {spec.product_type}")
        print(f"      quantity: {extracted.quantities[0] if extracted.quantities else 1}")
        print(f"      brand: {spec.brand or 'null'}")
        print(f"      model: {spec.model or 'null'}")
        print(f"      confidence: {spec.confidence:.2f}")
        print(f"      is_accessory: {extracted.is_accessory_only}")
    
    # v12: EARLY EXIT for accessories (detected by AI in same extraction call)
    if extracted.is_accessory_only:
        print(f"   🚫 AI Filter: Accessory detected → skipping")
        log.log_step("accessory_filtered", reason="ai_detected_accessory_only")
        run_logger.increment_stat("skipped_ai_accessory")
        return None  # Skip this listing
    
    log.log_step("extraction_result",
                 confidence=extracted.overall_confidence,
                 bundle_type=extracted.bundle_type.value,
                 products_found=len(extracted.products))
    
    # === DECISION GATE 1 ===
    next_step = decide_next_step(extracted, phase="initial")
    
    log.log_step("decision_gate_1",
                 confidence=extracted.overall_confidence,
                 decision=next_step)
    
    if next_step == "pricing":
        run_logger.increment_stat("ready_for_pricing")
        return extracted
    
    # === PHASE 2: DETAIL SCRAPING ===
    if next_step == "detail" and detail_scraper:
        log.log_escalation("initial", "detail_scraping",
                          f"confidence_{extracted.overall_confidence:.2f}_too_low")
        run_logger.increment_stat("needed_detail")
        
        # Scrape detail page
        detail_data = detail_scraper(listing.get("url", ""))
        
        if detail_data and detail_data.get("full_description"):
            # Re-extract with full description
            log.log_step("ai_extraction_with_detail")
            
            extracted = extract_product_with_ai(
                listing_id=listing_id,
                title=title,
                description=detail_data["full_description"]
            )
            
            extracted.extraction_method = "ai_with_detail"
            
            # CRITICAL: Store detail data in extracted object for DB persistence
            extracted.detail_data = {
                "seller_rating": detail_data.get("seller_rating"),
                "shipping_cost": detail_data.get("shipping_cost"),
                "pickup_available": detail_data.get("pickup_available"),
                "location": detail_data.get("location"),
                "full_description": detail_data.get("full_description", "")
            }
            
            log.log_ai_call(
                purpose="extraction_with_detail",
                model="claude-3-5-haiku-20241022",
                cost_usd=extracted.ai_cost_usd
            )
            
            # === DECISION GATE 2 ===
            next_step = decide_next_step(extracted, phase="after_detail")
            
            log.log_step("decision_gate_2",
                        confidence=extracted.overall_confidence,
                        decision=next_step)
            
            if next_step == "pricing":
                run_logger.increment_stat("ready_for_pricing")
                return extracted
    
    # === PHASE 3: VISION ANALYSIS ===
    if next_step == "vision" and vision_analyzer:
        image_url = listing.get("image_url") or (listing.get("image_urls", [None])[0])
        
        if image_url:
            log.log_escalation("detail", "vision",
                              f"confidence_{extracted.overall_confidence:.2f}_still_too_low")
            run_logger.increment_stat("needed_vision")
            
            # Analyze with vision
            vision_result = vision_analyzer(
                title=title,
                description=description,
                image_url=image_url
            )
            
            if vision_result and vision_result.get("success"):
                # Merge vision results into extracted
                # (Implementation depends on vision_result structure)
                extracted.overall_confidence = max(
                    extracted.overall_confidence,
                    vision_result.get("confidence", 0.0)
                )
                extracted.extraction_method = "ai_with_vision"
                
                log.log_step("vision_analysis",
                            confidence=vision_result.get("confidence", 0.0))
            
            # === DECISION GATE 3 ===
            next_step = decide_next_step(extracted, phase="after_vision")
            
            log.log_step("decision_gate_3",
                        confidence=extracted.overall_confidence,
                        decision=next_step)
            
            if next_step == "pricing":
                run_logger.increment_stat("ready_for_pricing")
                return extracted
    
    # === SKIP ===
    should_skip_listing, skip_reason = should_skip(extracted)
    
    if should_skip_listing:
        log.log_skip(skip_reason)
        run_logger.increment_stat("skipped")
        extracted.skip_reason = skip_reason
        return None
    
    return extracted


def process_batch(
    listings: List[Dict[str, Any]],
    run_id: str,
    detail_scraper=None,
    vision_analyzer=None
) -> tuple[List[ExtractedProduct], RunLogger]:
    """
    Process a batch of listings.
    
    Args:
        listings: List of raw listing data
        run_id: Unique run identifier
        detail_scraper: Optional detail scraper function
        vision_analyzer: Optional vision analyzer function
    
    Returns:
        (extracted_products, run_logger)
    """
    
    run_logger = RunLogger(run_id)
    run_logger.run_stats["total_listings"] = len(listings)
    
    extracted_products = []
    
    print(f"\n{'='*60}")
    print(f"🚀 PROCESSING {len(listings)} LISTINGS")
    print(f"{'='*60}\n")
    
    for i, listing in enumerate(listings, 1):
        listing_id = listing.get("listing_id", f"unknown_{i}")
        title = listing.get("title", "")[:50]
        
        print(f"[{i}/{len(listings)}] {listing_id}: {title}...")
        
        extracted = process_listing(
            listing=listing,
            run_logger=run_logger,
            detail_scraper=detail_scraper,
            vision_analyzer=vision_analyzer
        )
        
        if extracted:
            extracted_products.append(extracted)
            print(f"   ✅ Confidence: {extracted.overall_confidence:.2f} | {extracted.bundle_type.value}")
        else:
            print(f"   ⏭️ Skipped")
    
    # Finalize run statistics
    run_logger.finalize_run()
    
    return extracted_products, run_logger
