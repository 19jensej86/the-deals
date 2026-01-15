"""
Bundle Classifier - Conservative Bundle Detection
==================================================
Classifies bundles based on explicit patterns only.

CRITICAL: No domain assumptions, works for ANY product category.
"""

import re
from typing import Tuple, List
from models.bundle_types import BundleType
from models.product_spec import ProductSpec


def _interpret_number_in_title(title: str, number: int, unit: str) -> str:
    """
    P0.2: Determines if a number represents weight or quantity.
    
    CRITICAL: Prevents treating "30kg" as "30 pieces".
    
    Examples:
    - "30kg Hantelset" → weight (unit present)
    - "2x iPhone" → quantity (multiplier syntax)
    - "500 Stück Karten" → quantity (piece unit)
    - "15kg Gewicht" → weight (unit present)
    
    Args:
        title: Listing title
        number: The number found
        unit: The unit found (kg, g, x, stück, etc.)
    
    Returns:
        "weight" | "quantity" | "ambiguous"
    """
    title_lower = title.lower()
    
    # Explicit weight unit
    if unit in ["kg", "g", "lbs", "oz", "liter", "ml"]:
        return "weight"
    
    # Explicit quantity syntax
    if unit == "x":  # "2x iPhone"
        return "quantity"
    
    if unit in ["stück", "stk", "pieces", "pcs", "teile", "parts"]:
        return "quantity"
    
    # Ambiguous → require detail description
    return "ambiguous"


def classify_bundle(
    title: str,
    description: str,
    ai_extracted_products: List[ProductSpec]
) -> Tuple[BundleType, float, List[str]]:
    """
    Universal bundle classification.
    
    RULE: Conservative classification, no guessing.
    RULE: Multi-product ONLY if AI detected multiple different product_types.
    RULE: No regex heuristics on capitalization.
    
    Args:
        title: Listing title
        description: Listing description
        ai_extracted_products: Products extracted by AI
    
    Returns:
        (bundle_type, confidence, reasons)
    """
    
    title_lower = title.lower()
    reasons = []
    
    # === PATTERN 1: EXPLICIT QUANTITY ===
    # Universal patterns for quantity expressions
    quantity_patterns = [
        (r'\b([2-9]|[1-9][0-9])\s*x\s+', 'explicit_multiplier'),  # "2x ", "10x "
        (r'\blot\s+de\s+([2-9])\b', 'lot_de'),                    # "Lot de 2"
        (r'\b([2-9]|[1-9][0-9])\s+stk\.?\s', 'stueck'),           # "2 Stk."
        (r'\b([2-9]|[1-9][0-9])\s+stück\b', 'stueck'),            # "2 Stück"
        (r'\b([2-9]|[1-9][0-9])\s+pieces?\b', 'pieces'),          # "3 pieces"
        (r'\b([2-9]|[1-9][0-9])\s+pcs?\b', 'pcs'),                # "4 pcs"
    ]
    
    for pattern, pattern_name in quantity_patterns:
        match = re.search(pattern, title_lower)
        if match:
            qty = int(match.group(1))
            reasons.append(f"quantity_explicit_{qty}x_{pattern_name}")
            return (BundleType.QUANTITY, 0.95, reasons)
    
    # === PATTERN 2: BULK/LOT (ABSTRACT QUANTITY) ===
    # Large quantities without breakdown
    bulk_indicators = ['konvolut', 'bulk', 'sammlung', 'lot', 'collection']
    has_bulk_indicator = any(ind in title_lower for ind in bulk_indicators)
    
    # Check for large piece counts
    large_quantity_match = re.search(r'(\d+)\s*(stück|pieces|karten|cards|teile|parts)', title_lower)
    
    if has_bulk_indicator or (large_quantity_match and int(large_quantity_match.group(1)) > 50):
        # Bulk/Lot: Abstract quantity without details
        reasons.append("bulk_lot_large_quantity_no_details")
        return (BundleType.BULK_LOT, 0.60, reasons)
    
    # === PATTERN 3: WEIGHT-BASED (PHYSICAL TOTAL) ===
    # P0.2: Distinguish weight from quantity
    # CRITICAL: "30kg" is NOT "30 pieces"
    weight_patterns = [
        (r'(\d+)\s*kg\b', 'kg'),
        (r'(\d+)\s*g\b', 'g'),
        (r'(\d+)\s*liter\b', 'liter'),
    ]
    
    for pattern, unit in weight_patterns:
        match = re.search(pattern, title_lower)
        if match:
            amount = int(match.group(1))
            
            # P0.2: Verify this is weight, not quantity
            interpretation = _interpret_number_in_title(title, amount, unit)
            
            if interpretation != "weight":
                continue  # Not a weight-based bundle
            
            # Check: Are individual component specs present?
            # Example: "2x 15kg" means explicit quantity, not weight-based
            individual_pattern = r'\d+\s*x\s*\d+\s*' + unit
            has_individual = re.search(individual_pattern, title_lower)
            
            if has_individual:
                # Has explicit breakdown like "2x 15kg" → QUANTITY bundle
                continue
            
            # Weight-based bundle without component breakdown
            # This requires detail description for accurate pricing
            if amount > 10:
                reasons.append(f"weight_based_{amount}{unit}_needs_component_breakdown")
                return (BundleType.WEIGHT_BASED, 0.70, reasons)
    
    # === PATTERN 4: MULTI-PRODUCT (ONLY VIA AI) ===
    # RULE: Only if AI detected multiple different product_types
    if ai_extracted_products and len(ai_extracted_products) > 1:
        # Check: Are they really different product types?
        product_types = [p.product_type for p in ai_extracted_products]
        unique_types = set(product_types)
        
        if len(unique_types) > 1:
            reasons.append(f"multi_product_ai_detected_{len(unique_types)}_types")
            return (BundleType.MULTI_PRODUCT, 0.80, reasons)
    
    # === PATTERN 5: UNKNOWN ===
    # RULE: UNKNOWN only if:
    #   a) AI could not extract a product (len == 0 or very low confidence)
    #   b) Bundle structure exists but is ambiguous
    #
    # RULE: Marketing words ("Set", "Kit", "Bundle", "Paket") alone
    #       DO NOT cause UNKNOWN if AI extracted exactly ONE product.
    #
    # Check if AI extraction failed or is very uncertain
    if not ai_extracted_products:
        reasons.append("no_products_extracted_by_ai")
        return (BundleType.UNKNOWN, 0.20, reasons)
    
    if len(ai_extracted_products) == 1:
        product = ai_extracted_products[0]
        
        # If AI confidence is very low AND has uncertainty about bundle composition
        if product.confidence < 0.5 and any(
            field in product.uncertainty_fields 
            for field in ["bundle_composition", "included_items", "quantity"]
        ):
            reasons.append("low_confidence_bundle_composition_unclear")
            return (BundleType.UNKNOWN, 0.30, reasons)
    
    # === DEFAULT: SINGLE PRODUCT ===
    # If AI extracted exactly one product with reasonable confidence,
    # it's a single product regardless of marketing words like "Set".
    if len(ai_extracted_products) == 1:
        reasons.append("single_product_ai_extracted_one")
        return (BundleType.SINGLE_PRODUCT, 0.85, reasons)
    
    # Fallback for edge cases
    reasons.append("single_product_default")
    return (BundleType.SINGLE_PRODUCT, 0.80, reasons)
