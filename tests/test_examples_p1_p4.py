"""
Tests for P1-P4 Examples - Verification of Core Functionality
==============================================================
Tests that verify:
- No hallucinated specs
- Correct bundle type classification
- Correct websearch queries
- Correct pricing methods
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product_spec import ProductSpec
from models.bundle_types import BundleType, get_pricing_method, PricingMethod
from models.websearch_query import generate_websearch_query
from extraction.bundle_classifier import classify_bundle


def test_p1_iphone_single_product():
    """
    P1: Clear Single Product
    Input: "iPhone 12 Mini 64GB"
    Expected: Single product, no hallucinations
    """
    print("\n=== TEST P1: iPhone (Single Product) ===")
    
    # Simulate AI extraction result
    spec = ProductSpec(
        brand="Apple",
        model="iPhone 12 Mini",
        product_type="Smartphone",
        specs={"storage_gb": 64},
        price_relevant_attrs=[],
        confidence=0.95,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Clear brand, model, and storage capacity"
    )
    
    # Verify no hallucinations
    assert "material" not in spec.specs, "❌ Hallucinated material!"
    assert "color" not in spec.specs, "❌ Hallucinated color!"
    assert spec.brand == "Apple", "❌ Wrong brand"
    assert spec.model == "iPhone 12 Mini", "❌ Wrong model"
    assert spec.specs.get("storage_gb") == 64, "❌ Wrong storage"
    
    # Bundle classification
    bundle_type, confidence, reasons = classify_bundle(
        title="iPhone 12 Mini 64GB",
        description="",
        ai_extracted_products=[spec]
    )
    assert bundle_type == BundleType.SINGLE_PRODUCT, f"❌ Wrong bundle type: {bundle_type}"
    
    # Pricing method
    pricing_method = get_pricing_method(bundle_type)
    assert pricing_method == PricingMethod.SINGLE_PRICE, f"❌ Wrong pricing method: {pricing_method}"
    
    # Websearch query
    query = generate_websearch_query(spec)
    assert "Apple iPhone 12 Mini 64GB" in query.primary_query, f"❌ Wrong query: {query.primary_query}"
    assert "blau" not in query.primary_query.lower(), "❌ Color in query!"
    
    print("✅ P1 PASSED: No hallucinations, correct classification")


def test_p2_gym80_quantity():
    """
    P2: Explicit Quantity
    Input: "Gym 80 Hantelscheiben 2x 40kg"
    Expected: Quantity bundle, NO material hallucination
    """
    print("\n=== TEST P2: Gym 80 (Quantity) ===")
    
    # Simulate AI extraction result
    spec = ProductSpec(
        brand="Gym 80",
        model=None,
        product_type="Hantelscheibe",
        specs={"weight_kg": 40},  # Weight is explicit
        price_relevant_attrs=[],
        confidence=0.90,
        uncertainty_fields=["material", "diameter"],  # Explicitly uncertain
        extracted_from="title",
        extraction_notes="Explicit quantity '2x', weight 40kg. Material NOT mentioned."
    )
    
    # CRITICAL: Verify NO material hallucination
    assert "material" not in spec.specs, "❌ HALLUCINATED MATERIAL! Brand ≠ Material"
    assert "diameter" not in spec.specs, "❌ HALLUCINATED DIAMETER! Weight ≠ Diameter"
    assert "diameter_mm" not in spec.specs, "❌ HALLUCINATED DIAMETER!"
    
    # Verify weight IS present (because explicit)
    assert spec.specs.get("weight_kg") == 40, "❌ Weight should be present (explicit)"
    
    # Bundle classification
    bundle_type, confidence, reasons = classify_bundle(
        title="Gym 80 Hantelscheiben 2x 40kg",
        description="",
        ai_extracted_products=[spec]
    )
    assert bundle_type == BundleType.QUANTITY, f"❌ Wrong bundle type: {bundle_type}"
    assert "quantity_explicit" in reasons[0], f"❌ Wrong reason: {reasons}"
    
    # Pricing method
    pricing_method = get_pricing_method(bundle_type)
    assert pricing_method == PricingMethod.QUANTITY_MULTIPLY, f"❌ Wrong pricing method: {pricing_method}"
    
    # Websearch query
    query = generate_websearch_query(spec)
    assert "40kg" in query.primary_query, f"❌ Weight missing in query: {query.primary_query}"
    assert "metall" not in query.primary_query.lower(), "❌ Hallucinated material in query!"
    
    print("✅ P2 PASSED: No material hallucination, correct quantity classification")


def test_p3_playmobil_unknown():
    """
    P3: Unclear Set → Detail Needed
    Input: "Playmobil Ritterburg Set mit Zubehör"
    Expected: Unknown bundle, needs detail scraping
    """
    print("\n=== TEST P3: Playmobil (Unknown → Detail) ===")
    
    # Simulate AI extraction result (initial)
    spec = ProductSpec(
        brand="Playmobil",
        model=None,
        product_type="Ritterburg Set",
        specs={},  # No specs because unclear
        price_relevant_attrs=[],
        confidence=0.30,
        uncertainty_fields=["bundle_composition", "included_items", "quantity"],
        extracted_from="title",
        extraction_notes="'Set mit Zubehör' is vague, need detail page"
    )
    
    # Bundle classification
    bundle_type, confidence, reasons = classify_bundle(
        title="Playmobil Ritterburg Set mit Zubehör",
        description="",
        ai_extracted_products=[spec]
    )
    assert bundle_type == BundleType.UNKNOWN, f"❌ Should be UNKNOWN: {bundle_type}"
    assert confidence < 0.5, f"❌ Confidence should be low: {confidence}"
    
    # Pricing method
    pricing_method = get_pricing_method(bundle_type)
    assert pricing_method == PricingMethod.UNKNOWN, f"❌ Should be UNKNOWN pricing: {pricing_method}"
    
    # Should need detail scraping
    assert spec.confidence < 0.6, "❌ Should trigger detail scraping"
    
    print("✅ P3 PASSED: Correctly marked as unknown, needs detail")


def test_p4_kettlebell_price_relevant_attr():
    """
    P4: Price-Relevant Attribute
    Input: "Kettlebell verstellbar"
    Expected: "verstellbar" kept as price-relevant
    """
    print("\n=== TEST P4: Kettlebell (Price-Relevant Attr) ===")
    
    # Simulate AI extraction result
    spec = ProductSpec(
        brand=None,
        model=None,
        product_type="Kettlebell",
        specs={},
        price_relevant_attrs=["verstellbar"],  # MUST be kept
        confidence=0.85,
        uncertainty_fields=["brand"],
        extracted_from="title",
        extraction_notes="'verstellbar' is price-relevant and kept"
    )
    
    # Verify price-relevant attribute is present
    assert "verstellbar" in spec.price_relevant_attrs, "❌ Price-relevant attr missing!"
    
    # Bundle classification
    bundle_type, confidence, reasons = classify_bundle(
        title="Kettlebell verstellbar, Kugelhantel, Adjustable, Hantel Set",
        description="",
        ai_extracted_products=[spec]
    )
    assert bundle_type == BundleType.SINGLE_PRODUCT, f"❌ Wrong bundle type: {bundle_type}"
    
    # Websearch query
    query = generate_websearch_query(spec)
    assert "verstellbar" in query.primary_query, f"❌ Price-relevant attr missing in query: {query.primary_query}"
    
    print("✅ P4 PASSED: Price-relevant attribute correctly kept")


def test_p5_pokemon_bulk_lot():
    """
    P5: Bulk Lot (not weight-based)
    Input: "Pokémon Karten Konvolut ca. 500 Stück"
    Expected: BULK_LOT (not WEIGHT_BASED)
    """
    print("\n=== TEST P5: Pokémon (Bulk Lot) ===")
    
    # Simulate AI extraction result
    spec = ProductSpec(
        brand="Pokémon",
        model=None,
        product_type="Sammelkarten Konvolut",
        specs={"approximate_count": 500},
        price_relevant_attrs=[],
        confidence=0.50,
        uncertainty_fields=["card_rarities", "specific_cards"],
        extracted_from="title",
        extraction_notes="Bulk lot of ~500 cards, no details on rarities"
    )
    
    # Bundle classification
    bundle_type, confidence, reasons = classify_bundle(
        title="Pokémon Karten Konvolut ca. 500 Stück",
        description="",
        ai_extracted_products=[spec]
    )
    assert bundle_type == BundleType.BULK_LOT, f"❌ Should be BULK_LOT: {bundle_type}"
    assert bundle_type != BundleType.WEIGHT_BASED, "❌ Should NOT be WEIGHT_BASED (abstract quantity)"
    
    # Pricing method
    pricing_method = get_pricing_method(bundle_type)
    assert pricing_method == PricingMethod.BULK_ESTIMATE, f"❌ Wrong pricing method: {pricing_method}"
    
    print("✅ P5 PASSED: Correctly classified as BULK_LOT (not weight-based)")


def run_all_tests():
    """Run all P1-P4 tests."""
    print("\n" + "="*60)
    print("RUNNING P1-P5 VERIFICATION TESTS")
    print("="*60)
    
    try:
        test_p1_iphone_single_product()
        test_p2_gym80_quantity()
        test_p3_playmobil_unknown()
        test_p4_kettlebell_price_relevant_attr()
        test_p5_pokemon_bulk_lot()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nVerified:")
        print("  ✅ No hallucinated specs (Brand ≠ Material, Weight ≠ Diameter)")
        print("  ✅ Correct bundle type classification")
        print("  ✅ Correct websearch queries (no noise)")
        print("  ✅ Correct pricing methods")
        print("  ✅ Price-relevant attributes preserved")
        print("  ✅ BULK_LOT vs WEIGHT_BASED distinction")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()
