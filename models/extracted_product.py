"""
Extracted Product - Result of AI Extraction
============================================
Container for extraction results with uncertainty tracking.

CRITICAL: Can be empty (products=[]) if too unclear!
"""

from dataclasses import dataclass, field
from typing import List, Optional
from models.product_spec import ProductSpec
from models.bundle_types import BundleType


@dataclass
class ExtractedProduct:
    """
    Result of product extraction from a listing.
    
    IMPORTANT: Can be empty (products=[]) when unclear!
    """
    listing_id: str
    original_title: str
    
    # === PRODUCTS (CAN BE EMPTY) ===
    products: List[ProductSpec] = field(default_factory=list)
    quantities: List[int] = field(default_factory=list)  # Parallel to products
    
    # === BUNDLE CLASSIFICATION ===
    bundle_type: BundleType = BundleType.SINGLE_PRODUCT
    bundle_confidence: float = 0.0
    
    # === OVERALL ASSESSMENT ===
    overall_confidence: float = 0.0         # Min of all confidences
    can_price: bool = False                 # False if too unclear
    
    # === ESCALATION ===
    needs_detail_scraping: bool = False
    needs_vision: bool = False
    skip_reason: Optional[str] = None
    
    # === METADATA ===
    extraction_method: str = "ai_structured"  # "ai_structured", "ai_with_detail", "ai_with_vision"
    ai_cost_usd: float = 0.0
    
    def to_dict(self):
        """Convert to dictionary for serialization."""
        return {
            "listing_id": self.listing_id,
            "original_title": self.original_title,
            "products": [p.to_dict() for p in self.products],
            "quantities": self.quantities,
            "bundle_type": self.bundle_type.value,
            "bundle_confidence": self.bundle_confidence,
            "overall_confidence": self.overall_confidence,
            "can_price": self.can_price,
            "needs_detail_scraping": self.needs_detail_scraping,
            "needs_vision": self.needs_vision,
            "skip_reason": self.skip_reason,
            "extraction_method": self.extraction_method,
            "ai_cost_usd": self.ai_cost_usd,
        }
