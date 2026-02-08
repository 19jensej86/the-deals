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
    Stable product identity for deduplication.
    
    RULE: Generated from ProductSpec, NOT from Query or Domain.
    RULE: Specs included because EXPLICITLY mentioned, not category-based.
    """
    
    # === IDENTIFICATION ===
    product_key: str                        # Stable hash for deduplication
    # Format: "{brand}_{model}_{specs}" or "{product_type}_{specs}"
    # Examples:
    # "garmin_forerunner_970"
    # "hantelscheibe_40kg"
    # "iphone_12_mini_64gb"
    # "reifen_winter_18zoll"
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
        PHASE 4.2: Infer brand from model name using deterministic rules.
        
        Examples:
        - "iphone 12" -> "apple"
        - "galaxy watch" -> "samsung"
        - "pixel 7" -> "google"
        """
        text_lower = model_or_type.lower()
        
        # Deterministic brand inference rules
        BRAND_RULES = {
            "apple": ["iphone", "ipad", "airpods", "macbook", "apple watch", "imac"],
            "samsung": ["galaxy"],
            "google": ["pixel"],
            "sony": ["playstation", "wh-1000"],
            "garmin": ["fenix", "forerunner", "vivoactive"],
            "bose": ["quietcomfort", "soundlink"],
        }
        
        for brand, keywords in BRAND_RULES.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return brand
        
        return None
    
    def get_canonical_identity_key(self) -> str:
        """
        PHASE 4.2: Generate canonical identity key - SINGLE SOURCE OF TRUTH.
        
        Format: brand_model_tier_generation (underscore-separated)
        
        Rules:
        - Include: brand (inferred if missing), model, tier (mini/pro/max), generation
        - Exclude: storage, color, condition, marketing terms
        - Normalize: generations to gen_X format
        
        Examples:
        - "Apple iPhone 12 mini 128GB" -> "apple_iphone_12_mini"
        - "iPhone 12 Pro Max" -> "apple_iphone_12_pro_max"
        - "AirPods Pro (2nd Generation)" -> "apple_airpods_pro_gen_2"
        """
        # Start with websearch_base (brand + model/type)
        original = self.websearch_base.lower()
        base = original
        
        # Extract numeric tokens from original for corruption detection
        original_numbers = set(re.findall(r'\b\d+\b', original))
        
        # Normalize generations
        base = self.normalize_generation(base)
        
        # Remove color terms (not price-relevant)
        color_terms = ["schwarz", "weiss", "rot", "blau", "grün", "gelb", "grau", 
                       "black", "white", "red", "blue", "green", "yellow", "gray", "grey",
                       "silber", "silver", "gold", "rosa", "pink"]
        for color in color_terms:
            base = re.sub(r'\b' + color + r'\b', '', base)
        
        # Remove condition terms
        condition_terms = ["neu", "new", "gebraucht", "used", "wie neu", "ovp"]
        for cond in condition_terms:
            base = re.sub(r'\b' + cond + r'\b', '', base)
        
        # Remove marketing noise
        noise = ["top", "super", "mega", "original", "!!!"]
        for n in noise:
            base = base.replace(n, '')
        
        # Clean up whitespace
        base = ' '.join(base.split())
        
        # SAFETY GUARD: Verify no numeric corruption occurred
        result_numbers = set(re.findall(r'\b\d+\b', base))
        
        # Check if any original numbers were corrupted (shortened or changed)
        for orig_num in original_numbers:
            # Skip if this was a generation number (now converted to gen_X)
            if f'gen_{orig_num}' in base:
                continue
            
            # Check if the number is still present
            if orig_num not in result_numbers:
                # CORRUPTION DETECTED - fallback to safe identity
                print(f"   🚨 IDENTITY CORRUPTION DETECTED!")
                print(f"      Original: {original}")
                print(f"      Corrupted: {base}")
                print(f"      Missing number: {orig_num}")
                print(f"      Fallback: using websearch_base as-is")
                return original.replace(' ', '_').strip()
        
        # PHASE 4.2: Infer brand if missing
        if not self.brand_normalized:
            inferred_brand = self.infer_brand(base)
            if inferred_brand:
                # Prepend brand if not already present
                if not base.startswith(inferred_brand):
                    base = f"{inferred_brand} {base}"
        
        # Convert to underscore-separated format (canonical format)
        canonical = base.replace(' ', '_').replace('-', '_')
        
        # Remove duplicate underscores
        while '__' in canonical:
            canonical = canonical.replace('__', '_')
        
        return canonical.strip('_')
