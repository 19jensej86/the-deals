"""
Decision Gates - Escalation Logic
==================================
Determines next steps based on confidence thresholds.

CRITICAL: Conservative escalation, explicit skip reasons.
"""

import re
from models.extracted_product import ExtractedProduct
from models.bundle_types import BundleType


# Bundle detection keywords (German + English)
BUNDLE_KEYWORDS = [
    "set", "paket", "bundle", "lot", "konvolut", "sammlung",
    "2x", "3x", "4x", "5x", "6x", "10x", "paar", "stück",
    "inkl", "inklusive", "mit", "plus", "und", "&",
]


def _looks_like_bundle(title: str, description: str = "") -> bool:
    """Quick regex check if listing might be a bundle."""
    text = f"{title} {description}".lower()
    
    # Exclude quantity patterns like "2 Stk. à 2.5kg"
    if re.search(r'\d+\s*stk\.?\s*[àax@]\s*\d+', text):
        return False
    
    # Check for bundle keywords
    for kw in BUNDLE_KEYWORDS:
        if kw in text:
            if kw in ["stück", "stk"] and not re.search(r'\d+\s*(stück|stk)\s+\w+', text):
                continue
            return True
    
    # Quantity pattern with multiple items
    if re.search(r'\b(\d+)\s*(x|pcs|pieces?)\b', text):
        return True
    
    return False


class ConfidenceThresholds:
    """Universal thresholds for all product categories."""
    
    # After initial AI extraction
    READY_FOR_PRICING_INITIAL = 0.70
    
    # After detail scraping
    READY_FOR_PRICING_AFTER_DETAIL = 0.60
    
    # After vision
    MINIMUM_FOR_PRICING = 0.50
    
    # Below this: skip
    SKIP_THRESHOLD = 0.50


def decide_next_step(
    extracted: ExtractedProduct,
    phase: str,
    title: str = "",
    description: str = "",
    bundle_always_scrape_detail: bool = True
) -> str:
    """
    Determines next step based on confidence and phase.
    
    Args:
        extracted: Extracted product data
        phase: Current phase ("initial", "after_detail", "after_vision")
        title: Listing title for bundle pattern detection
        description: Listing description for bundle pattern detection
        bundle_always_scrape_detail: If True, always scrape detail for bundles
    
    Returns:
        Next step: "pricing", "detail", "vision", "skip"
    """
    conf = extracted.overall_confidence
    
    if phase == "initial":
        # After first AI extraction
        
        # BUNDLE FEATURE: Always scrape detail for listings that look like bundles
        # This ensures we get full component info before extraction
        if bundle_always_scrape_detail and _looks_like_bundle(title, description):
            return "detail"  # Force detail scraping for potential bundles
        
        # FIX 4: Bundles with empty components MUST have detail scraping
        if extracted.bundle_type != BundleType.SINGLE_PRODUCT:
            if not extracted.products or len(extracted.products) == 0:
                return "detail"  # Force detail scraping to extract components
        
        # P0.3: Weight-based bundles MUST have detail scraping
        # (to extract component breakdown from description)
        if extracted.bundle_type == BundleType.WEIGHT_BASED:
            return "detail"  # Required for accurate pricing
        
        # Unknown bundles need detail
        if extracted.bundle_type == BundleType.UNKNOWN:
            return "detail"
        
        # High confidence → ready for pricing
        if conf >= ConfidenceThresholds.READY_FOR_PRICING_INITIAL:
            return "pricing"
        
        # Low confidence → try detail scraping
        return "detail"
    
    elif phase == "after_detail":
        # After detail scraping
        if conf >= ConfidenceThresholds.READY_FOR_PRICING_AFTER_DETAIL:
            return "pricing"
        elif extracted.products and any(hasattr(p, 'image_url') for p in extracted.products):
            return "vision"
        else:
            return "skip"
    
    elif phase == "after_vision":
        # After vision analysis
        if conf >= ConfidenceThresholds.MINIMUM_FOR_PRICING:
            return "pricing"
        else:
            return "skip"
    
    return "skip"


def should_skip(extracted: ExtractedProduct) -> tuple[bool, str]:
    """
    Determines if listing should be skipped.
    
    Args:
        extracted: Extracted product data
    
    Returns:
        (should_skip, reason)
    """
    
    # Already marked for skip
    if extracted.skip_reason:
        return (True, extracted.skip_reason)
    
    # No products extracted
    if not extracted.products:
        return (True, "no_products_extracted")
    
    # FIX 4: Bundles with empty components after detail scraping = explicit skip
    if extracted.bundle_type != BundleType.SINGLE_PRODUCT:
        if not extracted.products or len(extracted.products) == 0:
            return (True, "bundle_components_empty_after_detail_scraping")
    
    # Confidence too low
    if extracted.overall_confidence < ConfidenceThresholds.SKIP_THRESHOLD:
        return (True, f"confidence_too_low_{extracted.overall_confidence:.2f}")
    
    # Bundle type unknown and can't price
    if extracted.bundle_type == BundleType.UNKNOWN and not extracted.can_price:
        return (True, "bundle_composition_unknown")
    
    return (False, "")
