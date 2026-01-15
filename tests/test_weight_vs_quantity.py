"""
Tests for P0.2: Weight vs Quantity Detection
=============================================
Verifies that weight (30kg) is NOT treated as quantity (30 pieces).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product_spec import ProductSpec
from models.bundle_types import BundleType
from extraction.bundle_classifier import classify_bundle, _interpret_number_in_title


def test_interpret_weight_unit():
    """P0.2: 30kg should be interpreted as weight, not quantity."""
    print("\n=== TEST: Interpret Weight Unit (kg) ===")
    
    result = _interpret_number_in_title("30kg Hantelset", 30, "kg")
    assert result == "weight", f"❌ Expected 'weight', got '{result}'"
    
    print(f"✅ PASSED: 30kg interpreted as weight")


def test_interpret_quantity_multiplier():
    """P0.2: 2x should be interpreted as quantity."""
    print("\n=== TEST: Interpret Quantity Multiplier (x) ===")
    
    result = _interpret_number_in_title("2x iPhone 12", 2, "x")
    assert result == "quantity", f"❌ Expected 'quantity', got '{result}'"
    
    print(f"✅ PASSED: 2x interpreted as quantity")


def test_interpret_quantity_stueck():
    """P0.2: 500 Stück should be interpreted as quantity."""
    print("\n=== TEST: Interpret Quantity (Stück) ===")
    
    result = _interpret_number_in_title("500 Stück Pokémon Karten", 500, "stück")
    assert result == "quantity", f"❌ Expected 'quantity', got '{result}'"
    
    print(f"✅ PASSED: 500 Stück interpreted as quantity")


def test_30kg_hantelset_not_30_pieces():
    """
    P0.2: CRITICAL TEST - 30kg Hantelset should be WEIGHT_BASED, not 30 pieces.
    
    This is the root cause of the 2776 CHF pricing explosion.
    """
    print("\n=== TEST: 30kg Hantelset NOT 30 Pieces ===")
    
    spec = ProductSpec(
        brand=None,
        model=None,
        product_type="Hantelset",
        specs={"weight_kg": 30},
        price_relevant_attrs=[],
        confidence=0.75,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="30kg total weight"
    )
    
    bundle_type, confidence, reasons = classify_bundle(
        title="30kg 3 in1 Hantelset Kurzhanteln + Langh. Supergrip Version",
        description="",
        ai_extracted_products=[spec]
    )
    
    # Should be WEIGHT_BASED (needs component breakdown)
    assert bundle_type == BundleType.WEIGHT_BASED, f"❌ Wrong bundle type: {bundle_type}"
    assert "needs_component_breakdown" in reasons[0], f"❌ Wrong reason: {reasons}"
    
    print(f"✅ PASSED: bundle_type = {bundle_type}")
    print(f"✅ PASSED: Requires component breakdown (not 30 pieces)")


def test_2x_iphone_is_quantity():
    """
    P0.2: 2x iPhone should be QUANTITY bundle (explicit multiplier).
    """
    print("\n=== TEST: 2x iPhone is QUANTITY ===")
    
    spec = ProductSpec(
        brand="Apple",
        model="iPhone 12",
        product_type="Smartphone",
        specs={"storage_gb": 64},
        price_relevant_attrs=[],
        confidence=0.95,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Explicit quantity"
    )
    
    bundle_type, confidence, reasons = classify_bundle(
        title="2x iPhone 12 64GB",
        description="",
        ai_extracted_products=[spec]
    )
    
    # Should be QUANTITY (explicit multiplier)
    assert bundle_type == BundleType.QUANTITY, f"❌ Wrong bundle type: {bundle_type}"
    assert "quantity_explicit" in reasons[0], f"❌ Wrong reason: {reasons}"
    
    print(f"✅ PASSED: bundle_type = {bundle_type}")


def test_2x_15kg_is_quantity_not_weight():
    """
    P0.2: "2x 15kg" has explicit breakdown → QUANTITY, not WEIGHT_BASED.
    """
    print("\n=== TEST: 2x 15kg is QUANTITY (explicit breakdown) ===")
    
    spec = ProductSpec(
        brand=None,
        model=None,
        product_type="Hantelscheiben",
        specs={"weight_kg": 15},
        price_relevant_attrs=[],
        confidence=0.90,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Explicit quantity with weight"
    )
    
    bundle_type, confidence, reasons = classify_bundle(
        title="Hantelscheiben (Bumper Plates), 2x 15kg, gummiert",
        description="",
        ai_extracted_products=[spec]
    )
    
    # Should be QUANTITY (has "2x 15kg" breakdown)
    assert bundle_type == BundleType.QUANTITY, f"❌ Wrong bundle type: {bundle_type}"
    
    print(f"✅ PASSED: bundle_type = {bundle_type}")
    print(f"✅ PASSED: Explicit breakdown detected (2x 15kg)")


def test_35kg_set_needs_breakdown():
    """
    P0.2: "35kg Set" without breakdown → WEIGHT_BASED (needs detail).
    """
    print("\n=== TEST: 35kg Set Needs Component Breakdown ===")
    
    spec = ProductSpec(
        brand="Gorilla Sports",
        model=None,
        product_type="Hantelscheiben",
        specs={"weight_kg": 35},
        price_relevant_attrs=[],
        confidence=0.85,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Total weight, no breakdown"
    )
    
    bundle_type, confidence, reasons = classify_bundle(
        title="Hantelscheiben Set 35kg Gripper von Gorilla Sports",
        description="",
        ai_extracted_products=[spec]
    )
    
    # Should be WEIGHT_BASED (needs component breakdown)
    assert bundle_type == BundleType.WEIGHT_BASED, f"❌ Wrong bundle type: {bundle_type}"
    assert "needs_component_breakdown" in reasons[0], f"❌ Wrong reason: {reasons}"
    
    print(f"✅ PASSED: bundle_type = {bundle_type}")
    print(f"✅ PASSED: Flagged for detail scraping")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("RUNNING P0.2 WEIGHT VS QUANTITY TESTS")
    print("="*60)
    
    test_interpret_weight_unit()
    test_interpret_quantity_multiplier()
    test_interpret_quantity_stueck()
    test_30kg_hantelset_not_30_pieces()
    test_2x_iphone_is_quantity()
    test_2x_15kg_is_quantity_not_weight()
    test_35kg_set_needs_breakdown()
    
    print("\n" + "="*60)
    print("✅ ALL P0.2 TESTS PASSED")
    print("="*60)
    print("\nVerified:")
    print("  ✅ 30kg interpreted as weight, NOT 30 pieces")
    print("  ✅ 2x interpreted as quantity multiplier")
    print("  ✅ Weight-based bundles flagged for component breakdown")
    print("  ✅ Explicit breakdowns (2x 15kg) classified as QUANTITY")
    print("  ✅ Prevents pricing explosion (30 × 89.9 CHF)")
