"""
Commodity detection helper for Phase 3 optimization.
Separated to avoid circular dependencies.
"""
import re
from typing import Optional


def is_commodity_variant(variant_key: str, category: str, websearch_query: Optional[str] = None) -> bool:
    """
    Check if variant is a commodity with stable prices.
    
    CONSERVATIVE DETECTION (CORRECTED):
    - Uses websearch_query (display_name) as primary signal, NOT variant_key
    - Only skips websearch when confident (explicit signals)
    - Ambiguous cases → do websearch (safe default)
    
    Commodities:
    1. Fitness weights with explicit weight in websearch_query
    2. Standard accessories (cables, adapters, bands)
    
    Args:
        variant_key: Product variant identifier (normalized, often generic)
        category: Category string (used cautiously)
        websearch_query: The actual search query string (display_name/final_search_name)
    
    Returns:
        bool: True if commodity (skip websearch), False otherwise
    """
    # Use websearch_query as primary signal (more specific than variant_key)
    search_text = (websearch_query or variant_key).lower()
    
    # SIGNAL 1: Explicit weight + fitness keywords = commodity
    # Example: "Hantelscheibe 5kg Gusseisen" or "Bumper Plate 20kg"
    has_explicit_weight = bool(re.search(r'\d+(?:[.,]\d+)?\s*kg', search_text))
    fitness_keywords = ["hantel", "gewicht", "plate", "scheibe", "bumper", "disc"]
    
    if has_explicit_weight and any(kw in search_text for kw in fitness_keywords):
        return True  # Commodity: stable CHF/kg pricing
    
    # SIGNAL 2: Accessory allowlist (stable prices, <50 CHF)
    accessory_keywords = [
        "kabel", "cable", "ladegerät", "charger", "adapter",
        "armband", "band", "strap",  # Watch bands
        "clip", "halter", "holder",
    ]
    if any(kw in search_text for kw in accessory_keywords):
        return True  # Commodity: accessories have stable prices
    
    # Default: NOT commodity (do websearch)
    # This includes:
    # - Generic patterns without explicit weight ("Weight Plates", "weight_plates")
    # - Electronics (prices vary)
    # - Clothing (sizes/styles vary)
    # - Any ambiguous case
    return False
