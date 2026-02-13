"""
Market pricing module - calculates resale prices from live auction data.
Extracted from ai_filter.py v8.0
"""

import statistics
from typing import Optional, Dict, Any, List


def calculate_market_resale_from_listings(
    identity_key: str,
    listings: List[Dict[str, Any]],
    reference_price: Optional[float] = None,
    unrealistic_floor: float = 10.0,
    context=None,
    ua: str = None,
    variant_new_price: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    PHASE 4.2: Calculate market resale price from listings with same identity_key.
    
    Aggregates across variants (e.g., iPhone 12 mini 128GB + 256GB together).
    Uses live bid data from current Ricardo auctions.
    """
    if not identity_key:
        return None
    
    # Filter listings by identity_key
    matching = [l for l in listings if l.get("_identity_key") == identity_key]
    
    print(f"         🔍 Filtering {len(listings)} listings for identity_key='{identity_key}'")
    print(f"         Matching listings: {len(matching)}")
    
    if not matching:
        print(f"         ❌ No matching listings found")
        return None
    
    # Collect bid samples with smart filtering
    # Strategy: Accept active auctions (bids_count > 0) with low floor (5 CHF)
    #           Accept starting bids (bids_count = 0) with high floor (unrealistic_floor)
    samples = []
    rejected_count = 0
    ACTIVE_AUCTION_MIN_PRICE = 5.0  # Low floor for auctions with active bids
    
    for listing in matching:
        bid = listing.get("current_bid")
        bids_count = listing.get("bids_count", 0)
        
        if not bid:
            rejected_count += 1
            print(f"         ❌ Rejected: bid={bid}, bids_count={bids_count}, reason=no_bid")
            continue
        
        # Accept if: Active auction (bids_count > 0) with reasonable price
        if bids_count > 0 and bid >= ACTIVE_AUCTION_MIN_PRICE:
            samples.append(bid)
            print(f"         ✅ Sample: bid={bid} CHF, bids_count={bids_count} (active auction)")
        # Accept if: Starting bid (bids_count = 0) but high enough to be realistic
        elif bids_count == 0 and bid >= unrealistic_floor:
            samples.append(bid)
            print(f"         ✅ Sample: bid={bid} CHF, bids_count={bids_count} (high starting bid)")
        else:
            rejected_count += 1
            if bids_count > 0:
                reason = f"below_active_floor (bid={bid} < {ACTIVE_AUCTION_MIN_PRICE})"
            else:
                reason = f"below_starting_floor (bid={bid} < {unrealistic_floor})"
            print(f"         ❌ Rejected: bid={bid}, bids_count={bids_count}, reason={reason}")
    
    print(f"         Valid samples: {len(samples)}, Rejected: {rejected_count}")
    
    if len(samples) < 2:
        print(f"         ❌ Insufficient samples ({len(samples)} < 2 required)")
        return None
    
    # Calculate median
    median_price = statistics.median(samples)
    
    return {
        "resale_price": round(median_price, 2),
        "source": "market_auction",
        "sample_size": len(samples),
        "market_based": True,
    }


def calculate_all_market_resale_prices(
    listings: List[Dict[str, Any]],
    variant_new_prices: Optional[Dict[str, float]] = None,
    unrealistic_floor: float = 10.0,
    typical_multiplier: float = 5.0,
    context=None,
    ua: str = None,
    query_analysis: Optional[Dict] = None,
    conn=None,
    run_id: str = None,
    get_new_price_estimate_fn=None,
    get_min_realistic_price_fn=None,
) -> Dict[str, Dict[str, Any]]:
    """
    PHASE 4.2: Aggregate market prices by canonical_identity_key.
    
    Uses cross-run DB data for each identity_key to enable market price aggregation.
    This allows listings with different storage/color to aggregate together.
    Example: iPhone 12 mini 128GB + iPhone 12 mini 256GB → same market price pool
    """
    # PHASE 4.2: Group by canonical_identity_key instead of variant_key
    identity_keys = set(l.get("_identity_key") for l in listings if l.get("_identity_key"))
    variant_new_prices = variant_new_prices or {}
    
    # Get reference price from query analysis
    reference_price = None
    if get_new_price_estimate_fn and query_analysis:
        reference_price = get_new_price_estimate_fn(query_analysis)
    
    if get_min_realistic_price_fn and query_analysis:
        unrealistic_floor = get_min_realistic_price_fn(query_analysis)
    
    # DEBUG: Market price aggregation diagnostics
    print(f"\n🔍 MARKET PRICE AGGREGATION DEBUG:")
    print(f"   Total listings: {len(listings)}")
    print(f"   Unique identity_keys: {len(identity_keys)}")
    print(f"   Unrealistic floor: {unrealistic_floor} CHF")
    if len(identity_keys) > 5:
        print(f"   Identity keys: {list(identity_keys)[:5]}...")
    else:
        print(f"   Identity keys: {list(identity_keys)}")
    
    results = {}
    for identity_key in identity_keys:
        print(f"\n   🔑 Processing identity_key: '{identity_key}'")
        
        # Use first variant_key for new price lookup (backwards compatibility)
        matching_listings = [l for l in listings if l.get("_identity_key") == identity_key]
        print(f"      Current run listings: {len(matching_listings)}")
        
        first_variant_key = matching_listings[0].get("variant_key") if matching_listings else None
        variant_new = variant_new_prices.get(first_variant_key) if matching_listings else None
        
        # CROSS-RUN FIX: Fetch persisted DB listings for this identity_key
        # This enables market price aggregation across runs (same as soft market)
        if conn and run_id:
            from db_pg_v2 import get_listings_by_search_identity
            db_listings = get_listings_by_search_identity(conn, run_id, identity_key)
            print(f"      DB listings fetched: {len(db_listings)}")
            
            # Combine current run + persisted listings
            all_listings_for_identity = matching_listings + db_listings
            
            # 🔍 OBSERVABILITY: Market aggregation sample validation
            unique_source_ids = len(set(
                l.get("listing_id") for l in all_listings_for_identity
                if l.get("listing_id") is not None
            ))
            
            print(f"      📊 MARKET SAMPLE STATS:")
            print(f"         Raw samples: {len(all_listings_for_identity)}")
            print(f"         Unique listings: {unique_source_ids}")
        else:
            # Fallback: use only current run listings
            all_listings_for_identity = matching_listings
            print(f"      ⚠️ No DB connection - using only current run listings")
        
        # Calculate market data using canonical identity (aggregates across variants)
        market_data = calculate_market_resale_from_listings(
            identity_key, all_listings_for_identity, reference_price, 
            unrealistic_floor, context, ua, variant_new
        )
        if market_data:
            results[identity_key] = market_data
            sample_count = market_data.get('sample_size', 0)
            print(f"      ✅ Market price calculated: {market_data['resale_price']} CHF ({sample_count} samples)")
        else:
            print(f"      ❌ No market price calculated (insufficient samples)")
    
    return results


def predict_final_auction_price(
    current_price: float,
    bids_count: int,
    hours_remaining: float,
    median_price: Optional[float] = None,
    new_price: Optional[float] = None,
    typical_multiplier: float = 5.0
) -> Dict[str, Any]:
    """Predict final auction price based on current bid, time, and activity."""
    if current_price <= 0:
        return {"predicted_final_price": 0.0, "confidence": 0.0}
    
    # Base multiplier based on time remaining
    if hours_remaining < 1:
        time_multiplier = 1.05
    elif hours_remaining < 24:
        time_multiplier = 1.15
    elif hours_remaining < 72:
        time_multiplier = 1.25
    else:
        time_multiplier = 1.35
    
    # Bid activity multiplier
    if bids_count >= 50:
        bid_multiplier = 1.20
    elif bids_count >= 20:
        bid_multiplier = 1.15
    elif bids_count >= 10:
        bid_multiplier = 1.10
    elif bids_count >= 5:
        bid_multiplier = 1.05
    else:
        bid_multiplier = 1.0
    
    # Calculate predicted price
    predicted = current_price * time_multiplier * bid_multiplier
    
    # Cap at median or new price if available
    if median_price and predicted > median_price * 1.2:
        predicted = median_price * 1.2
    elif new_price and predicted > new_price * 0.7:
        predicted = new_price * 0.7
    
    # Confidence based on data availability
    confidence = 0.5
    if median_price:
        confidence = 0.75
    if bids_count >= 10:
        confidence += 0.1
    
    return {
        "predicted_final_price": round(predicted, 2),
        "confidence": min(0.95, confidence)
    }


def calculate_soft_market_price(
    search_identity: str,
    all_listings_for_variant: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Calculate soft market price from current bids on similar listings."""
    if not search_identity or not all_listings_for_variant:
        return None
    
    # DEDUPLICATION: Remove duplicate listings by source_id (same listing from DB + current run)
    seen_source_ids = set()
    unique_listings = []
    for listing in all_listings_for_variant:
        source_id = listing.get("source_id") or listing.get("listing_id")
        if source_id and source_id in seen_source_ids:
            continue
        if source_id:
            seen_source_ids.add(source_id)
        unique_listings.append(listing)
    
    if len(unique_listings) < len(all_listings_for_variant):
        print(f"   SOFT MARKET: Deduplicated {len(all_listings_for_variant)} → {len(unique_listings)} unique listings")
    
    # Filter valid samples with bids
    valid_samples = []
    print(f"   SOFT MARKET DEBUG: Processing {len(unique_listings)} listings for identity='{search_identity}'")
    for idx, listing in enumerate(unique_listings):
        bid = listing.get("current_bid") or listing.get("current_price_ricardo")
        bids_count = listing.get("bids_count", 0)
        hours_remaining = listing.get("hours_remaining", 999)
        
        print(f"      [{idx}] bid={bid}, bids_count={bids_count}, hours_remaining={hours_remaining}")
        
        if not bid or bid <= 0 or bids_count == 0:
            print(f"      [{idx}] REJECTED: bid={bid}, bids_count={bids_count}")
            continue
        
        # Time adjustment factor
        if hours_remaining < 1:
            time_factor = 1.05
        elif hours_remaining < 24:
            time_factor = 1.10
        elif hours_remaining < 72:
            time_factor = 1.15
        else:
            time_factor = 1.20
        
        adjusted_bid = bid * time_factor
        valid_samples.append(adjusted_bid)
        print(f"      [{idx}] ACCEPTED: adjusted_bid={adjusted_bid:.2f}")
    
    print(f"   SOFT MARKET DEBUG: valid_samples count={len(valid_samples)}")
    
    # Require at least 2 samples
    if len(valid_samples) < 2:
        return None
    
    # Calculate median
    valid_samples.sort()
    median_idx = len(valid_samples) // 2
    if len(valid_samples) % 2 == 0:
        soft_price = (valid_samples[median_idx-1] + valid_samples[median_idx]) / 2
    else:
        soft_price = valid_samples[median_idx]
    
    # Confidence based on sample size
    if len(valid_samples) >= 5:
        confidence = 0.70
    elif len(valid_samples) >= 3:
        confidence = 0.60
    else:
        confidence = 0.50
    
    return {
        "soft_market_price": round(soft_price, 2),
        "confidence": confidence,
        "sample_count": len(valid_samples),
        "samples": valid_samples
    }


def apply_soft_market_cap(
    result: Dict[str, Any],
    soft_market_data: Dict[str, Any],
    search_identity: str
) -> Dict[str, Any]:
    """Apply soft market cap to resale price estimate (ceiling only)."""
    if not soft_market_data:
        return result
    
    soft_price = soft_market_data["soft_market_price"]
    soft_confidence = soft_market_data["confidence"]
    sample_count = soft_market_data["sample_count"]
    
    original_resale = result.get("resale_price_est", 0)
    if not original_resale or original_resale <= 0:
        return result
    
    # Safety factor: allow 10% above soft price
    safety_factor = 1.10
    soft_cap = soft_price * safety_factor
    
    # Only apply if current estimate exceeds soft cap
    if original_resale <= soft_cap:
        return result
    
    # Calculate cap impact
    cap_reduction_pct = (original_resale - soft_cap) / original_resale * 100
    
    # Store original before capping
    result["original_resale_before_cap"] = original_resale
    
    # Apply cap
    result["resale_price_est"] = soft_cap
    
    # Add soft market metadata
    result["soft_market_cap_applied"] = True
    result["soft_market_price"] = soft_price
    result["soft_market_confidence"] = soft_confidence
    result["soft_market_samples"] = sample_count
    result["cap_reduction_pct"] = cap_reduction_pct
    
    # Add marker to strategy_reason
    marker = f" | soft_market_cap: {original_resale:.2f} → {soft_cap:.2f} CHF (-{cap_reduction_pct:.0f}%, {sample_count} samples)"
    result["strategy_reason"] = result.get("strategy_reason", "") + marker
    
    return result
