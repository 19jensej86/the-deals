"""
Product Identity - Stable Deduplication Key
============================================
Generates stable product identifiers for deduplication.

CRITICAL: No domain assumptions. Specs included because EXPLICITLY mentioned,
          not because of product category.
"""

import re
from dataclasses import dataclass
from typing import Optional, Dict
from models.product_spec import ProductSpec


@dataclass
class ProductIdentity:
    """
    Two-Level Identity Model for Product Deduplication and Market Aggregation.
    ===========================================================================
    
    This class generates TWO distinct identity keys:
    
    1. product_key (persisted as variant_key in DB):
       - Exact SKU-level identity
       - Includes brand + model + ALL price-relevant specs
       - Used for: deduplication, component pricing, bundles
       - Example: "apple_iphone_12_mini_128GB" or "bosch_psb_550_re_18V"
    
    2. canonical_identity_key (persisted as identity_key in DB):
       - Market-level identity
       - Includes brand + model + market-defining specs ONLY
       - Excludes variant-level specs (storage, screen size, color, condition)
       - Used for: market aggregation, soft market pricing, competitive analysis
       - Example: "apple_iphone_12_mini" or "bosch_psb_550_re_18V"
    
    Market-Defining vs Variant-Level Specs:
    ----------------------------------------
    Market-defining specs = specs that change buyer use-case or market segment
      - voltage (18V vs 12V tools = different markets)
      - power_w (550W vs 750W = different tiers)
      - weight_kg (20kg vs 40kg plates = different products)
      - capacity_l (5L vs 10L = different use cases)
    
    Variant-level specs = specs that differentiate SKUs within same market
      - storage_gb (128GB vs 256GB iPhone = same market, different SKUs)
      - screen_size_inch (6.1" vs 6.7" = same model family)
      - color (Black vs White = same product)
    
    Why Both Keys Are Needed:
    -------------------------
    - variant_key: "What exact product is this?" (for pricing, deduplication)
    - identity_key: "What market does this compete in?" (for aggregation)
    
    Example:
    --------
    iPhone 12 mini 128GB Black:
      variant_key = "apple_iphone_12_mini_128GB"  (exact SKU)
      identity_key = "apple_iphone_12_mini"       (market group)
    
    Bosch PSB 550 RE 18V:
      variant_key = "bosch_psb_550_re_18V"  (exact SKU)
      identity_key = "bosch_psb_550_re_18V" (market group - voltage is market-defining)
    
    RULE: Generated from ProductSpec, NOT from Query or Domain.
    RULE: Specs included because EXPLICITLY mentioned, not category-based.
    """
    
    # === IDENTIFICATION ===
    product_key: str                        # Exact SKU identity (variant_key in DB)
    # Format: "{brand}_{model}_{all_specs}"
    # Examples:
    # "garmin_forerunner_970"
    # "hantelscheibe_40kg"
    # "iphone_12_mini_128GB"
    # "bosch_psb_550_re_18V"
    # "tasche"  # If no Brand/Model/Specs
    
    # === COMPONENTS ===
    brand_normalized: Optional[str]         # Lowercase, no spaces
    model_normalized: Optional[str]         # Lowercase, no spaces
    type_normalized: str                    # Lowercase, no spaces
    specs_normalized: Dict[str, str]        # Normalized specs for ID
    
    # === FOR WEBSEARCH ===
    websearch_base: str                     # Base for query generation
    
    @staticmethod
    def _is_clothing_size(key: str, value) -> bool:
        """
        Detects if a spec is a clothing size (NOT price-relevant).
        
        Clothing sizes (M, L, XL, 46, 98) have the SAME retail price.
        They affect availability, not value.
        
        Args:
            key: Spec key
            value: Spec value
        
        Returns:
            True if this is a clothing size that should be excluded
        """
        value_str = str(value).strip().upper()
        
        # Common clothing size patterns
        clothing_sizes = {
            # Letter sizes
            "XS", "S", "M", "L", "XL", "XXL", "XXXL",
            # Numeric sizes (European)
            "32", "34", "36", "38", "40", "42", "44", "46", "48", "50", "52", "54",
            "56", "58", "60", "62", "64", "66", "68",
            # Suit sizes
            "90", "94", "98", "102", "106", "110",
        }
        
        # Check if key explicitly indicates size
        if key in ["size", "size_clothing", "groesse", "taille"]:
            return True
        
        # Check if value matches clothing size pattern
        if value_str in clothing_sizes:
            return True
        
        return False
    
    @staticmethod
    def normalize_generation(text: str) -> str:
        """
        SAFE: Normalize generation expressions WITHOUT corrupting model numbers.
        
        ONLY matches generation patterns like:
        - "2nd generation" -> "gen_2"
        - "(2. Generation)" -> "gen_2"
        - "Second Generation" -> "gen_2"
        
        MUST NOT match standalone numbers in model names:
        - "iPhone 12" stays "iPhone 12" (NOT "iPhone 1")
        - "WH-1000XM4" stays "WH-1000XM4" (NOT "WH-100XM4")
        """
        text_lower = text.lower()
        
        # Pattern 1: "(2nd generation)" or "2nd gen" -> "gen_2"
        text_lower = re.sub(r'\(?([0-9]+)(?:st|nd|rd|th)\s+gen(?:eration)?\)?', r'gen_\1', text_lower)
        
        # Pattern 2: "(2. Generation)" -> "gen_2"
        text_lower = re.sub(r'\(?([0-9]+)\.\s+generation\)?', r'gen_\1', text_lower)
        
        # Pattern 3: "second generation" -> "gen_2"
        gen_words = {
            "first": "1", "second": "2", "third": "3", 
            "fourth": "4", "fifth": "5"
        }
        for word, num in gen_words.items():
            text_lower = re.sub(r'\b' + word + r'\s+gen(?:eration)?\b', f'gen_{num}', text_lower)
        
        return text_lower
    
    @staticmethod
    def _canonicalize_spec_value(key: str, value) -> str:
        """
        Canonicalizes spec value with proper unit casing.
        
        CRITICAL: Storage units MUST be uppercase (GB, TB, MB).
        CRITICAL: Voltage MUST be uppercase (V).
        CRITICAL: Weight units lowercase (kg, g).
        CRITICAL: Clothing sizes are EXCLUDED (not price-relevant).
        
        Args:
            key: Spec key (e.g., "storage_gb", "weight_kg")
            value: Spec value
        
        Returns:
            Canonicalized string for product_key, or None if should be excluded
        """
        value_str = str(value)
        
        # Storage: UPPERCASE (GB, TB, MB)
        if key == "storage_gb":
            # Extract number and ensure GB is uppercase
            match = re.match(r'(\d+)\s*([gGtTmM][bB])?', value_str)
            if match:
                num = match.group(1)
                return f"{num}GB"
            return f"{value_str}GB"
        
        # Voltage: UPPERCASE (V)
        elif key == "voltage":
            match = re.match(r'(\d+)\s*([vV])?', value_str)
            if match:
                num = match.group(1)
                return f"{num}V"
            return f"{value_str}V"
        
        # Weight: lowercase (kg, g)
        elif key == "weight_kg":
            match = re.match(r'(\d+(?:\.\d+)?)\s*([kK][gG])?', value_str)
            if match:
                num = match.group(1)
                return f"{num}kg"
            return f"{value_str}kg"
        
        # Screen size: lowercase with space
        elif key == "screen_size_inch":
            match = re.match(r'(\d+(?:\.\d+)?)\s*(inch|zoll)?', value_str, re.IGNORECASE)
            if match:
                num = match.group(1)
                return f"{num}_inch"
            return f"{value_str}_inch"
        
        # Generic: lowercase, replace spaces with underscores
        else:
            return value_str.lower().replace(" ", "_")
    
    @staticmethod
    def from_product_spec(spec: ProductSpec) -> 'ProductIdentity':
        """
        Generates stable ID from ProductSpec.
        
        RULE: Specs included because explicitly mentioned,
              NOT because of product category or domain knowledge.
        """
        parts = []
        specs_norm = {}
        
        # Brand (if present)
        if spec.brand:
            brand_norm = spec.brand.lower().replace(" ", "_")
            parts.append(brand_norm)
        
        # Model (if present)
        if spec.model:
            model_norm = spec.model.lower().replace(" ", "_")
            parts.append(model_norm)
        elif spec.product_type:
            type_norm = spec.product_type.lower().replace(" ", "_")
            parts.append(type_norm)
        
        # Specs (if present) - DOMAIN-AGNOSTIC
        # Include ALL explicitly mentioned specs, not just category-specific ones
        # CRITICAL: Use canonical unit formatting (GB not gb, V not v)
        # CRITICAL: Exclude clothing sizes (not price-relevant)
        for key, value in spec.specs.items():
            if value is not None:
                # P0.1: Filter out clothing sizes (not price-relevant)
                if ProductIdentity._is_clothing_size(key, value):
                    # Size is mentioned but NOT included in product_key or websearch
                    continue
                
                # Canonicalize spec value with proper unit casing
                value_norm = ProductIdentity._canonicalize_spec_value(key, value)
                specs_norm[key] = value_norm
                
                # Add to product_key
                parts.append(f"{value_norm}")
        
        product_key = "_".join(parts) if parts else "unknown_product"
        
        # Websearch base (for query generation)
        websearch_parts = []
        if spec.brand:
            websearch_parts.append(spec.brand)
        if spec.model:
            websearch_parts.append(spec.model)
        else:
            websearch_parts.append(spec.product_type)
        
        websearch_base = " ".join(websearch_parts)
        
        return ProductIdentity(
            product_key=product_key,
            brand_normalized=spec.brand.lower() if spec.brand else None,
            model_normalized=spec.model.lower() if spec.model else None,
            type_normalized=spec.product_type.lower(),
            specs_normalized=specs_norm,
            websearch_base=websearch_base
        )
    
    @staticmethod
    def infer_brand(model_or_type: str) -> str:
        """
        DEPRECATED: Brand inference removed - AI extraction handles this.
        
        The AI (Claude/GPT) already knows:
        - iPhone → Apple
        - Galaxy → Samsung
        - Pixel → Google
        - Fenix → Garmin
        
        If AI didn't extract brand, it's not clear enough from the listing.
        No fallback needed - trust AI judgment.
        """
        # No hardcoded rules - AI handles brand extraction
        return None
    
    def get_canonical_identity_key(self) -> str:
        """
        Generate market-level identity key (identity_key in DB).
        
        This groups variants that compete in the same market for aggregation and
        soft market pricing.
        
        Includes:
        - Brand (AI-extracted only - no fallback inference)
        - Model
        - ALL specs from AI extraction (AI already filters to price-relevant)
        
        Excludes:
        - Color (filtered out below)
        - Condition (filtered out below)
        - Clothing sizes (already filtered in from_product_spec)
        - Marketing noise (filtered out below)
        
        Examples:
        - "Apple iPhone 12 mini 128GB" -> "apple_iphone_12_mini_128GB"
        - "Bosch PSB 550 RE 18V" -> "bosch_psb_550_re_18V"
        - "Gym 80 Hantelscheiben 40kg" -> "gym_80_hantelscheiben_40kg"
        
        CRITICAL: No hardcoded spec lists. AI extraction determines price relevance.
        If AI extracted a spec, it's price-relevant for that product category.
        """
        parts = []
        
        # Brand (AI-extracted only - trust AI judgment)
        if self.brand_normalized:
            parts.append(self.brand_normalized)
        # No fallback inference - if AI didn't extract brand, it's not clear enough
        
        # Model (or product type if no model)
        if self.model_normalized:
            parts.append(self.model_normalized)
        else:
            parts.append(self.type_normalized)
        
        # ALL specs from AI extraction
        # AI already filtered to price-relevant specs in extraction prompt
        # No hardcoded list needed - works for ANY product category
        for spec_value in self.specs_normalized.values():
            parts.append(spec_value)
        
        # Join parts
        canonical = "_".join(parts)
        
        # Normalize generations (e.g., "2nd generation" -> "gen_2")
        canonical = self.normalize_generation(canonical)
        
        # Remove color terms (not market-defining)
        color_terms = ["schwarz", "weiss", "rot", "blau", "grün", "gelb", "grau", 
                       "black", "white", "red", "blue", "green", "yellow", "gray", "grey",
                       "silber", "silver", "gold", "rosa", "pink"]
        for color in color_terms:
            canonical = re.sub(r'\b' + color + r'\b', '', canonical, flags=re.IGNORECASE)
        
        # Remove condition terms (not market-defining)
        condition_terms = ["neu", "new", "gebraucht", "used", "wie_neu", "ovp"]
        for cond in condition_terms:
            canonical = re.sub(r'\b' + cond + r'\b', '', canonical, flags=re.IGNORECASE)
        
        # Remove marketing noise
        noise = ["top", "super", "mega", "original", "!!!"]
        for n in noise:
            canonical = canonical.replace(n, '')
        
        # Clean up: normalize separators and remove duplicates
        canonical = canonical.replace(' ', '_').replace('-', '_')
        while '__' in canonical:
            canonical = canonical.replace('__', '_')
        
        return canonical.strip('_').lower()
