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
