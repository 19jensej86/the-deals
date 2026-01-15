"""
Websearch Query - Shop-Optimized Search Strings
================================================
Generates optimized queries for web price searches.

CRITICAL: Generated from ProductSpec, NEVER from search.query.
"""

import re
from dataclasses import dataclass, field
from typing import List
from models.product_spec import ProductSpec
from models.product_identity import ProductIdentity


class UnitNormalization:
    """
    Rules for unit normalization in websearch queries.
    
    PRINCIPLE: Exactly as mentioned in title, OR neutralized.
    NO implicit conversions or language assumptions.
    
    CRITICAL: Storage units MUST be uppercase (GB, TB, MB).
    """
    
    # Units that are PRESERVED (exactly as mentioned)
    PRESERVE_UNITS = {
        # Weight
        "kg", "g", "lbs", "oz",
        # Length/Size
        "cm", "mm", "m", "inch", "zoll", '"', "'",
        # Volume
        "l", "liter", "ml", "gallon",
        # Storage (UPPERCASE)
        "GB", "TB", "MB",
        # Voltage
        "V", "volt",
    }
    
    # Unit synonyms (for normalization)
    UNIT_SYNONYMS = {
        "zoll": "inch",
        '"': "inch",
        "liter": "l",
    }
    
    @staticmethod
    def canonicalize_unit(value, unit: str) -> str:
        """
        Canonicalizes unit with proper casing for websearch and identity.
        
        RULE: Storage units MUST be uppercase (GB, TB, MB).
        RULE: Voltage MUST be uppercase (V).
        RULE: Weight units lowercase (kg, g).
        RULE: Use exactly the mentioned unit, or synonym.
        NO conversions (e.g., inch → cm).
        
        Args:
            value: Numeric value
            unit: Unit as mentioned in title
        
        Returns:
            Canonicalized string (e.g., "40kg", "6.1 inch", "18V", "64GB")
        """
        unit_lower = unit.lower().strip()
        
        # Synonym mapping
        if unit_lower in UnitNormalization.UNIT_SYNONYMS:
            unit_lower = UnitNormalization.UNIT_SYNONYMS[unit_lower]
        
        # Canonical formatting with proper casing
        # Storage: UPPERCASE, no space
        if unit_lower in ["gb", "tb", "mb"]:
            return f"{value}{unit_lower.upper()}"
        # Voltage: UPPERCASE, no space
        elif unit_lower in ["v", "volt"]:
            return f"{value}V"
        # Weight: lowercase, no space
        elif unit_lower in ["kg", "g"]:
            return f"{value}{unit_lower}"
        # Length/Size: lowercase, with space
        else:
            return f"{value} {unit_lower}"
    
    @staticmethod
    def normalize_unit(value, unit: str) -> str:
        """
        DEPRECATED: Use canonicalize_unit instead.
        Kept for backward compatibility.
        """
        return UnitNormalization.canonicalize_unit(value, unit)


@dataclass
class WebsearchQuery:
    """
    Optimized query for web price search.
    
    RULE: Generated from ProductSpec, NEVER from search.query.
    """
    product_identity: ProductIdentity
    
    # === QUERY VARIANTS ===
    primary_query: str                      # Main query
    fallback_queries: List[str] = field(default_factory=list)  # Alternative queries
    
    # === GENERATION LOGIC ===
    included_components: List[str] = field(default_factory=list)  # What's included
    removed_components: List[str] = field(default_factory=list)   # What's removed
    
    # === METADATA ===
    generation_confidence: float = 0.0      # How good is the query?
    expected_success_rate: float = 0.0      # Expected hit rate


def _is_color_attribute(key: str, value) -> bool:
    """
    Detects if a spec is a color (NOT price-relevant).
    
    Colors do NOT affect retail price:
    - Blue vs Red shirt: SAME price
    - Black vs White sneakers: SAME price
    
    Exception: Precious metals (gold, silver) ARE price-relevant.
    
    Args:
        key: Spec key
        value: Spec value
    
    Returns:
        True if this is a color that should be excluded from queries
    """
    value_str = str(value).strip().lower()
    
    # Common color names (German, English, French)
    colors = {
        # German
        "schwarz", "weiss", "rot", "blau", "grün", "gelb", "orange",
        "rosa", "pink", "lila", "violett", "braun", "grau", "beige",
        "türkis", "neongelb", "dunkelblau", "hellblau", "marine",
        # English
        "black", "white", "red", "blue", "green", "yellow", "orange",
        "pink", "purple", "brown", "gray", "grey", "beige", "turquoise",
        "navy", "neon", "dark", "light",
        # French
        "noir", "noire", "blanc", "blanche", "rouge", "bleu", "bleue",
        "vert", "verte", "jaune", "rose", "violet", "violette", "brun",
        "gris", "grise", "marine",
    }
    
    # Check if key explicitly indicates color
    if key in ["color", "colour", "farbe", "couleur"]:
        return True
    
    # Check if value matches color pattern
    if value_str in colors:
        return True
    
    # Exception: Precious metals ARE price-relevant
    precious_metals = {"gold", "silver", "platinum", "silber", "platin"}
    if value_str in precious_metals:
        return False
    
    return False


def generate_websearch_query(spec: ProductSpec) -> WebsearchQuery:
    """
    Generates optimal websearch query from ProductSpec.
    
    RULE: Only Brand + Model + price-relevant specs.
    RULE: No colors, sizes, conditions, marketing.
    RULE: Independent of search.query!
    
    Args:
        spec: Product specification
    
    Returns:
        Optimized websearch query
    """
    identity = ProductIdentity.from_product_spec(spec)
    
    # Start with base
    parts = [identity.websearch_base]
    included = ["brand", "model"] if spec.brand and spec.model else ["product_type"]
    removed = []
    
    # Add specs with units (using canonical formatting)
    for key, value in spec.specs.items():
        if value is None:
            continue
        
        # CRITICAL: Filter out colors (not price-relevant)
        if _is_color_attribute(key, value):
            removed.append(f"color:{value}")
            continue
        
        # CRITICAL: Filter out clothing sizes (not price-relevant)
        # Already handled in ProductIdentity, but double-check here
        if ProductIdentity._is_clothing_size(key, value):
            removed.append(f"size:{value}")
            continue
        
        # Weight
        if key == "weight_kg":
            parts.append(UnitNormalization.canonicalize_unit(value, "kg"))
            included.append("weight")
        
        # Screen size
        elif key == "screen_size_inch":
            parts.append(UnitNormalization.canonicalize_unit(value, "inch"))
            included.append("screen_size")
        
        # Storage (MUST be uppercase: GB, TB, MB)
        elif key == "storage_gb":
            parts.append(UnitNormalization.canonicalize_unit(value, "GB"))
            included.append("storage")
        
        # Voltage (MUST be uppercase: V)
        elif key == "voltage":
            # Extract unit from value (e.g., "18V" → 18, "V")
            match = re.match(r'(\d+)\s*([A-Za-z]+)', str(value))
            if match:
                num, unit = match.groups()
                parts.append(UnitNormalization.canonicalize_unit(num, unit))
                included.append("voltage")
        
        # Other specs (price-relevant only)
        else:
            # Keep only if not filtered above
            parts.append(str(value))
            included.append(key)
    
    # Add price-relevant attributes (with color filtering)
    for attr in spec.price_relevant_attrs:
        # CRITICAL: Filter out colors from price_relevant_attrs
        if _is_color_attribute("attr", attr):
            removed.append(f"attr_color:{attr}")
            continue
        
        # Filter out marketing fluff
        marketing_words = {"neu", "neuwertig", "top", "super", "ideal", "edel",
                          "new", "like new", "excellent", "perfect", "premium"}
        if attr.lower() in marketing_words:
            removed.append(f"marketing:{attr}")
            continue
        
        parts.append(attr)
        included.append(f"attr:{attr}")
    
    primary = " ".join(parts)
    
    # NOTE: Singularization is enforced at AI prompt level (extraction/ai_prompt.py)
    # AI is instructed to output product_type in SINGULAR form
    # No hardcoded regex rules here - scales to any category
    
    # Fallback queries
    fallbacks = []
    
    # Fallback 1: With product type
    if spec.model and spec.product_type:
        fallbacks.append(f"{spec.brand} {spec.model} {spec.product_type}")
    
    # Fallback 2: Without brand
    if spec.brand and spec.model:
        fallbacks.append(spec.model)
    
    # Confidence
    confidence = 0.5
    if spec.brand and spec.model:
        confidence = 0.95
    elif spec.brand or spec.model:
        confidence = 0.75
    
    return WebsearchQuery(
        product_identity=identity,
        primary_query=primary,
        fallback_queries=fallbacks,
        included_components=included,
        removed_components=removed,
        generation_confidence=confidence,
        expected_success_rate=confidence * 0.8
    )
