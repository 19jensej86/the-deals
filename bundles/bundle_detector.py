"""
Bundle detection and pricing module.
Extracted from ai_filter.py v8.0
"""

import re
import json
import statistics
from typing import Optional, Dict, Any, List

from utils_text import extract_weight_kg

# Constants
BUNDLE_KEYWORDS = [
    "set", "paket", "bundle", "lot", "konvolut", "sammlung",
    "2x", "3x", "4x", "5x", "6x", "10x", "paar", "stück",
    "inkl", "inklusive", "mit", "plus", "und", "&",
]

WEIGHT_PLATE_KEYWORDS = [
    "hantelscheibe", "gewichtsscheibe", "plate", "scheibe",
    "bumper", "gusseisen", "olympia", "weight",
]

WEIGHT_PRICING = {
    "bumper": {"new_price_per_kg": 6.0, "resale_rate": 0.60},
    "gummi": {"new_price_per_kg": 6.0, "resale_rate": 0.60},
    "rubber": {"new_price_per_kg": 6.0, "resale_rate": 0.60},
    "gusseisen": {"new_price_per_kg": 2.5, "resale_rate": 0.65},
    "cast iron": {"new_price_per_kg": 2.5, "resale_rate": 0.65},
    "eisen": {"new_price_per_kg": 2.5, "resale_rate": 0.65},
    "calibrated": {"new_price_per_kg": 12.0, "resale_rate": 0.55},
    "competition": {"new_price_per_kg": 12.0, "resale_rate": 0.55},
    "wettkampf": {"new_price_per_kg": 12.0, "resale_rate": 0.55},
    "urethane": {"new_price_per_kg": 8.0, "resale_rate": 0.55},
    "chrome": {"new_price_per_kg": 4.0, "resale_rate": 0.60},
    "chrom": {"new_price_per_kg": 4.0, "resale_rate": 0.60},
    "vinyl": {"new_price_per_kg": 2.0, "resale_rate": 0.50},
    "standard": {"new_price_per_kg": 3.5, "resale_rate": 0.60},
}

# Configuration - set by ai_filter
MAX_COMPONENT_PRICE = 2000.0
BUNDLE_DISCOUNT_PERCENT = 0.10
MAX_BUNDLE_RESALE_PERCENT_OF_NEW = 0.85


def set_bundle_config(max_component_price: float, bundle_discount: float, max_resale_pct: float):
    """Allow ai_filter to configure bundle pricing."""
    global MAX_COMPONENT_PRICE, BUNDLE_DISCOUNT_PERCENT, MAX_BUNDLE_RESALE_PERCENT_OF_NEW
    MAX_COMPONENT_PRICE = max_component_price
    BUNDLE_DISCOUNT_PERCENT = bundle_discount
    MAX_BUNDLE_RESALE_PERCENT_OF_NEW = max_resale_pct


def get_weight_type(name: str) -> str:
    """Detect weight plate type from name."""
    name_lower = name.lower()
    
    if any(kw in name_lower for kw in ["bumper", "gummi", "rubber"]):
        return "bumper"
    if any(kw in name_lower for kw in ["gusseisen", "cast iron", "eisen"]):
        return "gusseisen"
    if any(kw in name_lower for kw in ["calibrated", "competition", "wettkampf"]):
        return "calibrated"
    if "urethane" in name_lower:
        return "urethane"
    if any(kw in name_lower for kw in ["chrome", "chrom"]):
        return "chrome"
    if "vinyl" in name_lower:
        return "vinyl"
    
    return "standard"


def looks_like_bundle(title: str, description: str = "") -> bool:
    """Quick check if listing might be a bundle."""
    text = f"{title} {description}".lower()
    
    # v9.0 FIX: "2 Stk. à 2.5kg" = Quantity, NOT bundle!
    # Pattern: Zahl + Stk + à/x/@ + Gewicht = single product with quantity
    if re.search(r'\d+\s*stk\.?\s*[àax@]\s*\d+', text):
        return False
    
    # Check for real bundle keywords
    for kw in BUNDLE_KEYWORDS:
        if kw in text:
            # But exclude "stück/stk" if it's just quantity notation
            if kw in ["stück", "stk"] and not re.search(r'\d+\s*(stück|stk)\s+\w+', text):
                continue  # Skip - it's just "2 Stk." quantity
            return True
    
    # Quantity pattern - but only for real bundles with multiple items
    qty_pattern = r'\b(\d+)\s*(x|pcs|pieces?)\b'
    if re.search(qty_pattern, text):
        return True
    
    return False


def detect_bundle_with_ai(
    title: str,
    description: str,
    query: str,
    image_url: Optional[str] = None,
    use_vision: bool = False,
    query_analysis: Optional[Dict] = None,
    batch_result: Optional[Dict] = None,
    call_ai_fn=None,
    add_cost_fn=None,
    cost_haiku: float = 0.0,
) -> Dict[str, Any]:
    """
    Detect if listing is a bundle and identify components.
    
    v7.3.4: Can use pre-computed batch_result to avoid redundant AI calls.
    """
    result = {
        "is_bundle": False,
        "components": [],
        "confidence": 0.0,
    }
    
    # v7.3.4: Use batch result if available (cost optimization!)
    if batch_result is not None:
        return batch_result
    
    if not looks_like_bundle(title, description):
        return result
    
    if not call_ai_fn:
        return result
    
    # Fallback: Individual detection (only if batch wasn't used)
    prompt = f"""Analyze this Ricardo listing for bundle/set:

TITLE: {title}
DESCRIPTION: {description[:500] if description else "None"}
SEARCH TERM: {query}

Is this a bundle/set with multiple items?

If YES, list the components with estimated quantity.

Respond ONLY as JSON:
{{
  "is_bundle": true/false,
  "components": [
    {{"name": "Item 1", "quantity": 2, "unit": "pieces"}},
    {{"name": "Item 2", "quantity": 1, "unit": "pieces"}}
  ],
  "confidence": 0.0-1.0
}}"""

    try:
        raw = call_ai_fn(prompt, max_tokens=500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                if add_cost_fn and cost_haiku:
                    add_cost_fn(cost_haiku)
                
                result["is_bundle"] = parsed.get("is_bundle", False)
                result["components"] = parsed.get("components", [])
                result["confidence"] = parsed.get("confidence", 0.5)
    except Exception:
        pass  # Return default result on error
    
    return result


def _estimate_component_price(
    name: str, 
    category: str, 
    query_analysis: Optional[Dict] = None
) -> Optional[float]:
    """
    v7.3.3: Improved component price estimation.
    Uses weight-based pricing for fitness, smart defaults for other categories.
    """
    name_lower = name.lower()
    
    # ACCESSORIES (low value items) - handle first
    ACCESSORY_KEYWORDS = {
        "koffer": 15.0, "case": 15.0, "tasche": 15.0, "bag": 15.0, "etui": 15.0,
        "hülle": 15.0, "cover": 15.0, "schutzhülle": 15.0,
        "adapter": 10.0, "clip": 10.0, "halter": 10.0, "holder": 10.0,
        "kabel": 20.0, "cable": 20.0, "ladegerät": 20.0, "charger": 20.0, "ladekabel": 20.0,
        "armband": 25.0, "band": 25.0, "strap": 25.0, "wristband": 25.0,
        "anleitung": 0.0, "manual": 0.0, "handbuch": 0.0,
    }
    
    for keyword, price in ACCESSORY_KEYWORDS.items():
        if keyword in name_lower:
            return price
    
    # FITNESS: Weight-based pricing
    if category == "fitness" or any(kw in name_lower for kw in WEIGHT_PLATE_KEYWORDS):
        weight_kg = extract_weight_kg(name)
        if weight_kg and weight_kg > 0:
            weight_type = get_weight_type(name)
            pricing = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])
            if weight_type == "calibrated":
                return weight_kg * pricing["new_price_per_kg"] * 1.5
            return weight_kg * pricing["new_price_per_kg"]
        
        # Try quantity patterns like "4x 5kg"
        qty_weight = re.search(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', name_lower)
        if qty_weight:
            qty = int(qty_weight.group(1))
            per_kg = float(qty_weight.group(2).replace(',', '.'))
            total_kg = qty * per_kg
            return total_kg * 3.5
        
        # Fitness equipment defaults
        if any(kw in name_lower for kw in ["hantelscheibe", "gewicht", "plate", "scheibe"]):
            return None  # Weight plate without weight = invalid
        if any(kw in name_lower for kw in ["hantelstange", "langhantel", "barbell", "stange"]):
            return 80.0
        if any(kw in name_lower for kw in ["kurzhantel", "dumbbell", "gymnastikhantel"]):
            return 15.0
        if any(kw in name_lower for kw in ["bank", "bench", "rack"]):
            return 150.0
        if any(kw in name_lower for kw in ["ständer", "halterung", "stand"]):
            return 60.0
        if any(kw in name_lower for kw in ["set", "kit"]):
            return 80.0
        return 40.0
    
    # ELECTRONICS
    if category == "electronics":
        if "forerunner" in name_lower:
            if any(m in name_lower for m in ["965", "955", "945"]):
                return 500.0
            if any(m in name_lower for m in ["935", "735", "645"]):
                return 200.0
            return 300.0
        if "fenix" in name_lower:
            if "7" in name_lower or "8" in name_lower:
                return 600.0
            if "6" in name_lower:
                return 400.0
            if "5" in name_lower:
                return 250.0
            return 400.0
        if "vivofit" in name_lower:
            return 80.0
        if "vivoactive" in name_lower:
            return 250.0
        if "brustgurt" in name_lower or "heart rate" in name_lower:
            return 50.0
        if "armband" in name_lower or "band" in name_lower:
            return 25.0
        if "ladekabel" in name_lower or "charger" in name_lower:
            return 20.0
        return 100.0
    
    # CLOTHING
    if category == "clothing":
        if any(kw in name_lower for kw in ["jacke", "jacket", "mantel", "coat"]):
            return 150.0
        if any(kw in name_lower for kw in ["hose", "jeans", "pants"]):
            return 80.0
        if any(kw in name_lower for kw in ["pullover", "sweater", "hoodie"]):
            return 90.0
        if any(kw in name_lower for kw in ["hemd", "shirt", "bluse"]):
            return 70.0
        return 60.0
    
    return 50.0


def _adjust_price_for_model_year(name: str, price: float, category: str) -> float:
    """Adjust price based on detected model year (for electronics)."""
    if category != "electronics" or not price:
        return price
    
    name_lower = name.lower()
    
    if "fenix" in name_lower:
        if "5" in name_lower:
            return min(price, 250.0)
        if "6" in name_lower:
            return min(price, 450.0)
        if "7" in name_lower:
            return min(price, 650.0)
    
    if "forerunner" in name_lower:
        if any(m in name_lower for m in ["235", "230", "220"]):
            return min(price, 150.0)
        if any(m in name_lower for m in ["935", "735"]):
            return min(price, 200.0)
        if any(m in name_lower for m in ["945", "745"]):
            return min(price, 350.0)
    
    return price


def _get_component_resale_rate(name: str, category: str, default_rate: float) -> float:
    """Get resale rate for a specific component type."""
    name_lower = name.lower()
    
    # Accessories have lower resale value
    if any(kw in name_lower for kw in ["armband", "band", "kabel", "cable", "charger", "adapter"]):
        return 0.30
    
    # Main fitness equipment holds value well
    if category == "fitness":
        if any(kw in name_lower for kw in ["hantelscheibe", "gewicht", "plate", "bumper"]):
            return 0.60
        if any(kw in name_lower for kw in ["bank", "bench", "rack"]):
            return 0.50
    
    # Electronics depreciate based on age
    if category == "electronics":
        if "fenix 5" in name_lower or "forerunner 935" in name_lower:
            return 0.55
        if "fenix 6" in name_lower or "forerunner 945" in name_lower:
            return 0.50
    
    return default_rate


def _get_market_price_for_component(
    conn, 
    run_id: str, 
    identity_key: str
) -> Optional[Dict[str, Any]]:
    """Get market price for a component by identity_key."""
    try:
        from db_pg_v2 import get_listings_by_search_identity
        
        db_listings = get_listings_by_search_identity(conn, run_id, identity_key)
        
        if len(db_listings) < 2:
            return None
        
        samples = []
        for listing in db_listings:
            bid = listing.get("current_bid")
            bids_count = listing.get("bids_count", 0)
            
            if bid and bids_count > 0 and bid >= 5.0:
                samples.append(bid)
        
        if len(samples) < 2:
            return None
        
        median_price = statistics.median(samples)
        
        return {
            "resale_price": round(median_price, 2),
            "sample_size": len(samples),
            "source": "market_auction",
        }
    except Exception as e:
        print(f"      Market lookup failed for {identity_key}: {e}")
        return None


def _calculate_weight_price(weight_kg: float, material: str) -> float:
    """Calculate new price for weight plates based on weight and material."""
    material_lower = material.lower() if material else "standard"
    
    WEIGHT_PRICING_LOCAL = {
        "bumper": 6.0, "gummi": 6.0, "rubber": 6.0,
        "gusseisen": 2.5, "cast iron": 2.5, "eisen": 2.5,
        "calibrated": 12.0, "competition": 12.0, "wettkampf": 12.0,
        "urethane": 8.0,
        "chrome": 4.0, "chrom": 4.0,
        "vinyl": 2.0,
        "standard": 3.5,
    }
    
    price_per_kg = WEIGHT_PRICING_LOCAL.get(material_lower, 3.5)
    return round(weight_kg * price_per_kg, 2)


def price_bundle_components_v2(
    components: List,  # List[BundleComponent]
    category: Optional[str] = None,
    query_analysis: Optional[Dict] = None,
    conn=None,
    run_id: str = None,
    get_resale_rate_fn=None,
) -> List:
    """
    v8.0: Price bundle components using market data + weight-based fallbacks.
    
    Pricing Priority (per component):
    1. market_auction: Median of concurrent auctions with same identity_key
    2. weight_based: For fitness weights (CHF/kg × weight)
    3. ai_estimate: Fallback estimation
    """
    from models.bundle_component import BundleComponent
    
    resale_rate = 0.60
    if get_resale_rate_fn and query_analysis:
        resale_rate = get_resale_rate_fn(query_analysis)
    
    is_fitness = category == "fitness" if category else False
    
    priced = []
    
    for comp in components:
        # Skip invalid components
        if not comp.product_type or comp.quantity <= 0:
            print(f"      Skipping invalid component: {comp.display_name}")
            continue
        
        # === PRIORITY 1: Market data lookup ===
        market_price = None
        if conn and run_id and comp.identity_key:
            market_price = _get_market_price_for_component(conn, run_id, comp.identity_key)
        
        if market_price:
            comp.resale_price = market_price["resale_price"]
            comp.price_source = "market_auction"
            print(f"      {comp.display_name}: {comp.resale_price:.2f} CHF (market, n={market_price.get('sample_size', 0)})")
        
        # === PRIORITY 2: Weight-based pricing for fitness ===
        elif is_fitness and comp.product_type in ["hantelscheibe", "kurzhantel", "kettlebell"]:
            weight_kg = comp.specs.get("weight_kg")
            if weight_kg and weight_kg > 0:
                material = comp.specs.get("material", "standard")
                new_price = _calculate_weight_price(weight_kg, material)
                comp.new_price = new_price
                comp.resale_price = new_price * 0.60
                comp.price_source = "weight_based"
                print(f"      {comp.display_name}: {comp.resale_price:.2f} CHF ({weight_kg}kg × rate)")
            else:
                print(f"      {comp.display_name}: No weight specified, skipping")
                continue
        
        # === PRIORITY 3: AI estimation fallback ===
        else:
            est_new = _estimate_component_price(comp.display_name, category or "general", query_analysis)
            if est_new and est_new > 0:
                comp.new_price = est_new
                component_resale_rate = _get_component_resale_rate(comp.display_name, category or "general", resale_rate)
                comp.resale_price = est_new * component_resale_rate
                comp.price_source = "ai_estimate"
                print(f"      {comp.display_name}: {comp.resale_price:.2f} CHF (AI estimate)")
            else:
                print(f"      {comp.display_name}: Price unavailable, skipping")
                continue
        
        # Calculate unit_value (resale × quantity)
        comp.calculate_unit_value()
        
        # Validate: Skip if unit_value is unreasonable
        if comp.unit_value and comp.unit_value > MAX_COMPONENT_PRICE * comp.quantity:
            print(f"      {comp.display_name}: Value {comp.unit_value:.2f} exceeds max, skipping")
            continue
        
        priced.append(comp)
    
    return priced


def calculate_bundle_new_price(priced_components: List[Dict[str, Any]]) -> float:
    """Calculate total new price for bundle."""
    if not priced_components:
        return 0.0
    
    total = sum(c.get("total_new", 0) for c in priced_components)
    return round(total, 2)


def calculate_bundle_resale(priced_components: List[Dict[str, Any]], bundle_new_price: float) -> float:
    """Calculate bundle resale price with discount."""
    if not priced_components:
        return 0.0
    
    # Sum component resale prices
    component_total = sum(c.get("total_resale", 0) for c in priced_components)
    
    # Apply bundle discount (people pay less for bundles)
    bundle_resale = component_total * (1 - BUNDLE_DISCOUNT_PERCENT)
    
    # Cap at max percent of new price
    max_resale = bundle_new_price * MAX_BUNDLE_RESALE_PERCENT_OF_NEW
    if bundle_resale > max_resale:
        bundle_resale = max_resale
    
    return round(bundle_resale, 2)
