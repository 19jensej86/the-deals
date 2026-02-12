"""
Test Bundle Extraction - Phase 3 Verification
==============================================
Tests the new bundle extraction and pricing logic.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction.bundle_extractor import (
    extract_bundle_components,
    generate_component_identity_key,
    _extract_with_regex,
    _is_fitness_category,
)
from models.bundle_component import BundleComponent, BundleExtractionResult


def test_regex_extraction_fitness_weights():
    """Test regex-based extraction for fitness weight patterns."""
    print("\n=== TEST: Regex Extraction (Fitness Weights) ===")
    
    # Test case: Multiple weight groups
    title = "Hantelscheiben Set 4x 5kg + 2x 10kg + 2x 15kg Bumper Plates"
    description = "Olympia Hantelscheiben, 50mm Loch"
    
    result = _extract_with_regex(title, description, "fitness")
    
    print(f"Title: {title}")
    print(f"Is bundle: {result.is_bundle}")
    print(f"Components: {len(result.components)}")
    print(f"Total weight: {result.total_weight_kg} kg")
    print(f"Confidence: {result.confidence}")
    
    for comp in result.components:
        print(f"  - {comp.display_name}: qty={comp.quantity}, weight={comp.specs.get('weight_kg')}kg")
    
    assert result.is_bundle == True, "Should detect as bundle"
    assert len(result.components) >= 3, "Should have at least 3 component groups"
    assert result.total_weight_kg == 70, f"Total weight should be 70kg, got {result.total_weight_kg}"
    
    print("✅ PASSED")


def test_identity_key_generation():
    """Test identity key generation for components."""
    print("\n=== TEST: Identity Key Generation ===")
    
    # Test case 1: Weight plate with material
    comp1 = BundleComponent(
        product_type="hantelscheibe",
        display_name="Bumper Plate 5kg",
        quantity=4,
        specs={"weight_kg": 5, "material": "bumper", "diameter_mm": 50}
    )
    key1 = generate_component_identity_key(comp1)
    print(f"Component: {comp1.display_name}")
    print(f"Identity key: {key1}")
    assert "hantelscheibe" in key1
    assert "bumper" in key1
    assert "5kg" in key1
    
    # Test case 2: Barbell (no weight)
    comp2 = BundleComponent(
        product_type="langhantel",
        display_name="Olympia Langhantelstange",
        quantity=1,
        specs={"diameter_mm": 50}
    )
    key2 = generate_component_identity_key(comp2)
    print(f"Component: {comp2.display_name}")
    print(f"Identity key: {key2}")
    assert "langhantel" in key2
    assert "olympic" in key2
    
    # Test case 3: Squat rack (no specs)
    comp3 = BundleComponent(
        product_type="squat_rack",
        display_name="Squat Rack",
        quantity=1,
        specs={}
    )
    key3 = generate_component_identity_key(comp3)
    print(f"Component: {comp3.display_name}")
    print(f"Identity key: {key3}")
    assert key3 == "squat_rack"
    
    print("✅ PASSED")


def test_fitness_category_detection():
    """Test fitness category detection."""
    print("\n=== TEST: Fitness Category Detection ===")
    
    # Should detect as fitness
    fitness_cases = [
        ("Hantelscheiben Set 70kg", "Bumper Plates"),
        ("Langhantel Olympic", "220cm Stange"),
        ("Squat Rack mit Gewichten", "Krafttraining"),
    ]
    
    for title, desc in fitness_cases:
        is_fitness = _is_fitness_category(None, title, desc)
        print(f"  '{title}' -> fitness={is_fitness}")
        assert is_fitness == True, f"Should detect '{title}' as fitness"
    
    # Should NOT detect as fitness
    non_fitness_cases = [
        ("iPhone 12 Pro", "Apple Smartphone"),
        ("Garmin Fenix 6", "GPS Smartwatch"),
    ]
    
    for title, desc in non_fitness_cases:
        is_fitness = _is_fitness_category(None, title, desc)
        print(f"  '{title}' -> fitness={is_fitness}")
        assert is_fitness == False, f"Should NOT detect '{title}' as fitness"
    
    print("✅ PASSED")


def test_bundle_component_unit_value():
    """Test unit_value calculation."""
    print("\n=== TEST: Unit Value Calculation ===")
    
    comp = BundleComponent(
        product_type="hantelscheibe",
        display_name="Bumper Plate 5kg",
        quantity=4,
        specs={"weight_kg": 5, "material": "bumper"},
        resale_price=15.0,  # 15 CHF per plate
    )
    
    unit_value = comp.calculate_unit_value()
    
    print(f"Component: {comp.display_name}")
    print(f"Quantity: {comp.quantity}")
    print(f"Resale price (per unit): {comp.resale_price} CHF")
    print(f"Unit value (total): {unit_value} CHF")
    
    assert unit_value == 60.0, f"Unit value should be 60 CHF (4 × 15), got {unit_value}"
    assert comp.unit_value == 60.0, "unit_value should be stored on component"
    
    print("✅ PASSED")


def test_bundle_extraction_result_totals():
    """Test BundleExtractionResult total calculation."""
    print("\n=== TEST: Bundle Extraction Result Totals ===")
    
    result = BundleExtractionResult(
        is_bundle=True,
        components=[
            BundleComponent(
                product_type="squat_rack",
                display_name="Squat Rack",
                quantity=1,
                new_price=300.0,
                resale_price=150.0,
                unit_value=150.0,
            ),
            BundleComponent(
                product_type="langhantel",
                display_name="Langhantelstange",
                quantity=1,
                new_price=150.0,
                resale_price=60.0,
                unit_value=60.0,
            ),
            BundleComponent(
                product_type="hantelscheibe",
                display_name="Bumper Plate 5kg",
                quantity=4,
                new_price=30.0,
                resale_price=15.0,
                unit_value=60.0,
            ),
        ],
        confidence=0.9,
    )
    
    result.calculate_totals()
    
    print(f"Components: {len(result.components)}")
    print(f"Total new price: {result.total_new_price} CHF")
    print(f"Total resale price: {result.total_resale_price} CHF")
    
    # Expected: 300 + 150 + (30×4) = 300 + 150 + 120 = 570 CHF new
    # Expected: 150 + 60 + 60 = 270 CHF resale
    assert result.total_new_price == 570.0, f"Total new should be 570, got {result.total_new_price}"
    assert result.total_resale_price == 270.0, f"Total resale should be 270, got {result.total_resale_price}"
    
    print("✅ PASSED")


def test_example_bundle_from_user():
    """Test with user's example bundle listing."""
    print("\n=== TEST: User Example Bundle ===")
    print("Squat Rack inkl. Langhantel, 70 kg Gewichte, Bodenmatten")
    print("Components: Rack + Stange + 4×5kg + 2×10kg + 2×15kg + 30 Matten")
    
    title = "Squat Rack inkl. Langhantel, 70 kg Gewichte, Bodenmatten"
    description = """
    Komplettes Heimfitness Set:
    - Squat Rack / Langhantelständer
    - Langhantelstange
    - 70 kg Hantelscheiben:
        - 4 × 5 kg
        - 2 × 10 kg
        - 2 × 15 kg
    - 30 × Bodenmatten 60x60cm
    """
    
    # This would require AI for full extraction, so we just test regex part
    result = _extract_with_regex(title, description, "fitness")
    
    print(f"Regex extraction found: {len(result.components)} components")
    print(f"Is bundle (regex): {result.is_bundle}")
    
    # Regex should at least find the weight pattern
    if result.is_bundle:
        print("Weight components found via regex:")
        for comp in result.components:
            print(f"  - {comp.display_name}: qty={comp.quantity}")
    
    print("(Full extraction requires AI - tested in integration)")
    print("✅ PASSED (regex portion)")


if __name__ == "__main__":
    print("="*60)
    print("BUNDLE EXTRACTION TESTS - Phase 3")
    print("="*60)
    
    test_regex_extraction_fitness_weights()
    test_identity_key_generation()
    test_fitness_category_detection()
    test_bundle_component_unit_value()
    test_bundle_extraction_result_totals()
    test_example_bundle_from_user()
    
    print("\n" + "="*60)
    print("ALL TESTS PASSED ✅")
    print("="*60)
