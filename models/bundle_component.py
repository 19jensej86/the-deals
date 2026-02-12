"""
Bundle Component Model - Query-Agnostic Component Representation
================================================================
Structured representation of individual bundle components with pricing.

CRITICAL: Language-agnostic internally, German-aware for Ricardo matching.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class BundleComponent:
    """
    Single component of a bundle listing.
    
    Example: In a "Squat Rack + Langhantel + 70kg Gewichte" bundle:
    - Component 1: Squat Rack (qty: 1)
    - Component 2: Langhantelstange (qty: 1)
    - Component 3: Hantelscheibe 5kg (qty: 4)
    - Component 4: Hantelscheibe 10kg (qty: 2)
    - Component 5: Hantelscheibe 15kg (qty: 2)
    """
    
    # === IDENTIFICATION ===
    product_type: str                       # Normalized type: "hantelscheibe", "langhantel", etc.
    display_name: str                       # Original name from listing: "Bumper Plates 5kg"
    identity_key: Optional[str] = None      # For market aggregation: "hantelscheibe_bumper_5kg"
    variant_key: Optional[str] = None       # Brand-specific if known
    
    # === QUANTITY & SPECS ===
    quantity: int = 1
    specs: Dict[str, Any] = field(default_factory=dict)
    # Specs examples:
    # - weight_kg: 5.0 (for weights)
    # - material: "bumper" | "gusseisen" | "calibrated"
    # - size_cm: 60 (for mats)
    # - length_cm: 220 (for barbells)
    
    # === PRICING (populated during evaluation) ===
    new_price: Optional[float] = None       # New/retail price per unit
    resale_price: Optional[float] = None    # Resale price per unit
    unit_value: Optional[float] = None      # Total value: resale × quantity
    price_source: str = "unknown"           # "market_auction", "web_single", "ai_estimate", etc.
    
    # === METADATA ===
    confidence: float = 0.0                 # AI confidence in extraction
    category: Optional[str] = None          # Product category for pricing logic
    
    def calculate_unit_value(self) -> Optional[float]:
        """Calculate total value for this component."""
        if self.resale_price is not None and self.quantity > 0:
            self.unit_value = round(self.resale_price * self.quantity, 2)
            return self.unit_value
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "product_type": self.product_type,
            "display_name": self.display_name,
            "identity_key": self.identity_key,
            "variant_key": self.variant_key,
            "quantity": self.quantity,
            "specs": self.specs,
            "new_price": self.new_price,
            "resale_price": self.resale_price,
            "unit_value": self.unit_value,
            "price_source": self.price_source,
            "confidence": self.confidence,
            "category": self.category,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BundleComponent":
        """Create BundleComponent from dictionary."""
        return cls(
            product_type=data.get("product_type", "unknown"),
            display_name=data.get("display_name", data.get("name", "Unknown")),
            identity_key=data.get("identity_key"),
            variant_key=data.get("variant_key"),
            quantity=data.get("quantity", 1),
            specs=data.get("specs", {}),
            new_price=data.get("new_price"),
            resale_price=data.get("resale_price"),
            unit_value=data.get("unit_value"),
            price_source=data.get("price_source", "unknown"),
            confidence=data.get("confidence", 0.0),
            category=data.get("category"),
        )


@dataclass
class BundleExtractionResult:
    """
    Result of bundle component extraction.
    
    Contains all extracted components and metadata about the extraction.
    """
    
    is_bundle: bool = False
    components: List[BundleComponent] = field(default_factory=list)
    confidence: float = 0.0
    extraction_method: str = "none"         # "ai_text", "ai_vision", "regex"
    category: Optional[str] = None          # Detected category
    total_weight_kg: Optional[float] = None # For weight-based bundles
    
    # === AGGREGATED VALUES (populated after pricing) ===
    total_new_price: Optional[float] = None
    total_resale_price: Optional[float] = None
    
    def calculate_totals(self) -> None:
        """Calculate aggregate values from components."""
        if not self.components:
            return
        
        new_total = 0.0
        resale_total = 0.0
        
        for comp in self.components:
            if comp.new_price is not None:
                new_total += comp.new_price * comp.quantity
            if comp.unit_value is not None:
                resale_total += comp.unit_value
            elif comp.resale_price is not None:
                resale_total += comp.resale_price * comp.quantity
        
        self.total_new_price = round(new_total, 2) if new_total > 0 else None
        self.total_resale_price = round(resale_total, 2) if resale_total > 0 else None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_bundle": self.is_bundle,
            "components": [c.to_dict() for c in self.components],
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "category": self.category,
            "total_weight_kg": self.total_weight_kg,
            "total_new_price": self.total_new_price,
            "total_resale_price": self.total_resale_price,
        }
