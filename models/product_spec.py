"""
Product Specification - Query-Agnostic Data Model
==================================================
Structured product data extracted from listings.

CRITICAL RULES:
- Only extract what is EXPLICITLY mentioned
- No hallucinations (Brand ≠ Material, Weight ≠ Diameter)
- No domain assumptions
- Uncertainty is valid
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class ProductSpec:
    """
    Structured product data - ONLY from listing extraction.
    
    RULE: All fields Optional. Only set if EXPLICITLY mentioned.
    RULE: No inferences from Query, Brand, or Context.
    """
    
    # === IDENTITY (from title extracted) ===
    brand: Optional[str] = None              # "Garmin", "Tommy Hilfiger", "Gym 80"
    model: Optional[str] = None              # "Forerunner 970", "Fenix 7"
    product_type: str = ""                   # "Smartwatch", "Hantelscheibe", "Schal"
    
    # === SPECIFICATIONS (ONLY if explicitly mentioned) ===
    # IMPORTANT: No derivations! Only explicit mentions.
    specs: Dict[str, Any] = field(default_factory=dict)
    # Examples:
    # {"weight_kg": 40} - if "40kg" in title
    # {"screen_size_inch": 6.1} - if "6.1 Zoll" in title
    # {"storage_gb": 64} - if "64GB" in title
    # {"voltage": "18V"} - if "18V" in title
    
    # FORBIDDEN:
    # {"material": "Metall"} - if not mentioned
    # {"diameter_mm": 50} - if not mentioned
    # {"variant": "Sapphire"} - if not mentioned
    
    # === PRICE-RELEVANT ATTRIBUTES (ONLY if explicitly mentioned) ===
    price_relevant_attrs: List[str] = field(default_factory=list)
    # Examples: ["Solar", "Sapphire", "verstellbar", "Titan"]
    # NOT allowed: inferred from brand, price, or category
    
    # === UNCERTAINTY ===
    confidence: float = 0.0                  # 0.0-1.0
    uncertainty_fields: List[str] = field(default_factory=list)
    # ["material", "variant", "bundle_composition"]
    
    # === METADATA ===
    extracted_from: str = "title"           # "title", "description", "detail_page", "vision"
    extraction_notes: str = ""              # Reasoning for decisions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "brand": self.brand,
            "model": self.model,
            "product_type": self.product_type,
            "specs": self.specs,
            "price_relevant_attrs": self.price_relevant_attrs,
            "confidence": self.confidence,
            "uncertainty_fields": self.uncertainty_fields,
            "extracted_from": self.extracted_from,
            "extraction_notes": self.extraction_notes,
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'ProductSpec':
        """Create from dictionary."""
        return ProductSpec(
            brand=data.get("brand"),
            model=data.get("model"),
            product_type=data.get("product_type", ""),
            specs=data.get("specs", {}),
            price_relevant_attrs=data.get("price_relevant_attrs", []),
            confidence=data.get("confidence", 0.0),
            uncertainty_fields=data.get("uncertainty_fields", []),
            extracted_from=data.get("extracted_from", "title"),
            extraction_notes=data.get("extraction_notes", ""),
        )
