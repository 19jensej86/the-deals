"""
Market Price Calculator - v5.2
==============================
PRIORITY for resale_price_est:

1. MARKET DATA from Ricardo (search for similar listings)
2. Cached market data (from previous runs)
3. AI estimate using resale_rate (LAST RESORT)

This module handles the market-based pricing logic.
"""

import statistics
from typing import List, Dict, Any, Optional


def calculate_variant_market_price(
    variant_key: str,
    listings_in_batch: List[Dict[str, Any]],
    context=None,
    ua: str = None,
    min_samples: int = 3,
    min_realistic_price: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """
    Calculates market resale price for a variant.
    
    PRIORITY:
    1. Pure buy-now prices from batch (same variant_key)
    2. If not enough: Search Ricardo for more samples
    3. Mixed buy-now prices (auction + buy-now combos)
    
    Returns None if not enough data (caller should use AI fallback).
    """
    
    # =========================================================================
    # STEP 1: Collect prices from current batch
    # =========================================================================
    pure_buynow = []  # Listings with ONLY buy-now (no auction)
    combo_buynow = []  # Listings with both auction and buy-now
    
    for listing in listings_in_batch:
        if listing.get("variant_key") != variant_key:
            continue
        
        bn = listing.get("buy_now_price")
        cp = listing.get("current_price_ricardo")
        
        if bn is not None and bn >= min_realistic_price:
            if cp is None or cp == 0:
                pure_buynow.append(float(bn))
            else:
                combo_buynow.append(float(bn))
    
    # =========================================================================
    # STEP 2: If not enough, search Ricardo for more
    # =========================================================================
    total_samples = len(pure_buynow) + len(combo_buynow)
    
    if total_samples < min_samples and context is not None:
        # Extract search term from variant_key (e.g., "Garmin|Forerunner 935" -> "Garmin Forerunner 935")
        search_term = variant_key.replace("|", " ")
        
        try:
            from scrapers.ricardo import search_ricardo_for_prices
            
            print(f"   🔍 Searching Ricardo for '{search_term}' market prices...")
            
            additional_prices = search_ricardo_for_prices(
                search_term=search_term,
                context=context,
                ua=ua,
                max_results=10,
                buy_now_only=True,  # Only pure buy-now for accuracy
                min_price=min_realistic_price,
            )
            
            if additional_prices:
                # Filter out prices we already have (rough dedup)
                existing = set(pure_buynow + combo_buynow)
                new_prices = [p for p in additional_prices if p not in existing]
                pure_buynow.extend(new_prices)
                print(f"   ✅ Found {len(new_prices)} additional buy-now prices")
                
        except ImportError:
            print(f"   ⚠️ search_ricardo_for_prices not available")
        except Exception as e:
            print(f"   ⚠️ Market search failed: {e}")
    
    # =========================================================================
    # STEP 3: Calculate median
    # =========================================================================
    
    # Prefer pure buy-now (most reliable)
    if len(pure_buynow) >= min_samples:
        median = statistics.median(pure_buynow)
        return {
            "resale_price": round(median, 2),
            "source": "market_buynow_pure",
            "sample_size": len(pure_buynow),
            "samples": pure_buynow,
            "market_based": True,
        }
    
    # Fall back to mixed
    all_buynow = pure_buynow + combo_buynow
    if len(all_buynow) >= 2:  # Lower threshold for mixed
        median = statistics.median(all_buynow)
        return {
            "resale_price": round(median, 2),
            "source": "market_buynow_mixed",
            "sample_size": len(all_buynow),
            "samples": all_buynow,
            "market_based": True,
        }
    
    # Not enough data
    return None


def calculate_all_variant_market_prices(
    variant_keys: List[str],
    listings_in_batch: List[Dict[str, Any]],
    context=None,
    ua: str = None,
    min_samples: int = 3,
    min_realistic_price: float = 10.0,
) -> Dict[str, Dict[str, Any]]:
    """
    Calculates market prices for all variants.
    
    Returns dict mapping variant_key -> market data (or empty if not enough data).
    """
    results = {}
    
    for vk in variant_keys:
        if not vk:
            continue
        
        market_data = calculate_variant_market_price(
            variant_key=vk,
            listings_in_batch=listings_in_batch,
            context=context,
            ua=ua,
            min_samples=min_samples,
            min_realistic_price=min_realistic_price,
        )
        
        if market_data:
            results[vk] = market_data
            print(f"   📊 {vk}: {market_data['resale_price']} CHF "
                  f"({market_data['source']}, n={market_data['sample_size']})")
    
    return results


def get_best_resale_price(
    variant_key: str,
    market_prices: Dict[str, Dict[str, Any]],
    variant_info: Optional[Dict[str, Any]],
    new_price: Optional[float],
    resale_rate: float = 0.40,
) -> Dict[str, Any]:
    """
    Gets the best available resale price estimate.
    
    PRIORITY:
    1. Market data (from market_prices dict)
    2. Cached resale (from variant_info)
    3. AI estimate (new_price * resale_rate)
    
    Returns: {"resale_price": X, "source": "market|cache|estimate", "market_based": bool}
    """
    
    # Priority 1: Market data
    if variant_key and variant_key in market_prices:
        market = market_prices[variant_key]
        return {
            "resale_price": market["resale_price"],
            "source": market["source"],
            "market_based": True,
            "sample_size": market.get("sample_size", 0),
        }
    
    # Priority 2: Cached variant info
    if variant_info and variant_info.get("resale_price"):
        return {
            "resale_price": variant_info["resale_price"],
            "source": "cache" if variant_info.get("market_based") else "cache_estimate",
            "market_based": variant_info.get("market_based", False),
            "sample_size": variant_info.get("market_sample_size", 0),
        }
    
    # Priority 3: AI estimate from new price
    if new_price and new_price > 0:
        estimated = round(new_price * resale_rate, 2)
        return {
            "resale_price": estimated,
            "source": f"estimate_{resale_rate*100:.0f}%",
            "market_based": False,
            "sample_size": 0,
        }
    
    # No data available
    return {
        "resale_price": None,
        "source": "none",
        "market_based": False,
        "sample_size": 0,
    }