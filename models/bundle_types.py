"""
Bundle Types and Pricing Methods - Query-Agnostic
==================================================
Defines bundle classification and pricing strategies.

CRITICAL: No domain assumptions, works for ANY product category.
"""

from enum import Enum


class BundleType(Enum):
    """
    Universal bundle classification.
    
    RULE: Conservative classification, no guessing.
    """
    
    SINGLE_PRODUCT = "single_product"
    # 1 product, quantity 1
    # Examples: "iPhone 12", "Bosch Akkuschrauber", "Playmobil Ritterburg"
    
    QUANTITY = "quantity"
    # 1 product type, quantity > 1 (EXPLICIT)
    # Examples: "2x iPhone 12", "Lot de 3 Akkuschrauber", "4 Stück Reifen"
    # RULE: Quantity must be EXPLICIT ("2x", "3 Stück", "Lot de 4")
    
    WEIGHT_BASED = "weight_based"
    # Total weight/volume without breakdown
    # Examples: "156kg Hantelscheiben Set"
    # RULE: Physical total (kg, g, liter) without individual specs
    # NOT for abstract quantities like "500 cards"
    
    BULK_LOT = "bulk_lot"
    # Abstract quantity without breakdown
    # Examples: "500 Pokémon Karten Konvolut", "Lego Bulk 5kg"
    # RULE: Large quantity (>50 pieces) without details
    # Pricing: Bulk estimate, not unit price × quantity
    
    MULTI_PRODUCT = "multi_product"
    # Multiple different products
    # Examples: "Smartwatch + Fitness-Tracker"
    # RULE: Only if AI detected multiple different product_types
    
    UNKNOWN = "unknown"
    # Unclear from title
    # Examples: "Werkzeug Set", "Elektronik Paket"
    # RULE: When uncertain → UNKNOWN, not best guess


class PricingMethod(Enum):
    """
    Pricing methods for different bundle types.
    """
    
    SINGLE_PRICE = "single_price"
    # 1 product → 1 price
    
    QUANTITY_MULTIPLY = "quantity_multiply"
    # Quantity × unit price
    # Example: 2x iPhone → 2 × 800 CHF = 1600 CHF
    
    SUM_OF_PARTS = "sum_of_parts"
    # Sum of all individual prices
    # Example: Smartwatch + Tracker → 300 CHF + 150 CHF = 450 CHF
    
    WEIGHT_BASED_ESTIMATE = "weight_based_estimate"
    # Estimate based on total weight
    # Example: 156kg Set → price per kg × 156kg
    
    BULK_ESTIMATE = "bulk_estimate"
    # Bulk estimate for large quantities
    # Example: 500 cards → bulk price (not 500 × unit price)
    
    UNKNOWN = "unknown"
    # Cannot be priced


def get_pricing_method(bundle_type: BundleType) -> PricingMethod:
    """
    Determines pricing method based on bundle type.
    
    Args:
        bundle_type: Bundle classification
    
    Returns:
        Appropriate pricing method
    """
    mapping = {
        BundleType.SINGLE_PRODUCT: PricingMethod.SINGLE_PRICE,
        BundleType.QUANTITY: PricingMethod.QUANTITY_MULTIPLY,
        BundleType.MULTI_PRODUCT: PricingMethod.SUM_OF_PARTS,
        BundleType.WEIGHT_BASED: PricingMethod.WEIGHT_BASED_ESTIMATE,
        BundleType.BULK_LOT: PricingMethod.BULK_ESTIMATE,
        BundleType.UNKNOWN: PricingMethod.UNKNOWN,
    }
    
    return mapping.get(bundle_type, PricingMethod.UNKNOWN)
