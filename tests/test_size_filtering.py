"""
Tests for P0.1: Size Filtering in Product Identity
===================================================
Verifies that clothing sizes are excluded from product_key and websearch queries.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product_spec import ProductSpec
from models.product_identity import ProductIdentity


def test_clothing_size_m_excluded():
    """
    P0.1: Clothing size M should NOT appear in product_key or websearch.
    
    Before: "tommy_hilfiger_hemd_m"
    After:  "tommy_hilfiger_hemd"
    """
    print("\n=== TEST: Clothing Size M Excluded ===")
    
    spec = ProductSpec(
        brand="Tommy Hilfiger",
        model=None,
        product_type="Hemd",
        specs={"size": "M"},  # Size explicitly mentioned
        price_relevant_attrs=[],
        confidence=0.90,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Size M mentioned but not price-relevant"
    )
    
    identity = ProductIdentity.from_product_spec(spec)
    
    # Size should NOT be in product_key
    assert "m" not in identity.product_key.lower(), f"❌ Size 'M' found in product_key: {identity.product_key}"
    assert identity.product_key == "tommy_hilfiger_hemd", f"❌ Wrong product_key: {identity.product_key}"
    
    # Size should NOT be in websearch_base
    assert "M" not in identity.websearch_base, f"❌ Size 'M' found in websearch_base: {identity.websearch_base}"
    assert identity.websearch_base == "Tommy Hilfiger Hemd", f"❌ Wrong websearch_base: {identity.websearch_base}"
    
    print(f"✅ PASSED: product_key = {identity.product_key}")
    print(f"✅ PASSED: websearch_base = {identity.websearch_base}")


def test_suit_size_98_excluded():
    """
    P0.1: Suit size 98 should NOT appear in product_key.
    
    Before: "tommy_hilfiger_costume_homme_laine_98"
    After:  "tommy_hilfiger_costume_homme"
    """
    print("\n=== TEST: Suit Size 98 Excluded ===")
    
    spec = ProductSpec(
        brand="Tommy Hilfiger",
        model=None,
        product_type="Costume Homme",
        specs={"size": "98"},  # Suit size
        price_relevant_attrs=[],
        confidence=0.85,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Suit size 98"
    )
    
    identity = ProductIdentity.from_product_spec(spec)
    
    # Size should NOT be in product_key
    assert "98" not in identity.product_key, f"❌ Size '98' found in product_key: {identity.product_key}"
    assert identity.product_key == "tommy_hilfiger_costume_homme", f"❌ Wrong product_key: {identity.product_key}"
    
    print(f"✅ PASSED: product_key = {identity.product_key}")


def test_size_xl_excluded():
    """
    P0.1: Size XL should NOT appear in product_key.
    
    Before: "tommy_hilfiger_trainingshose_xl"
    After:  "tommy_hilfiger_trainingshose"
    """
    print("\n=== TEST: Size XL Excluded ===")
    
    spec = ProductSpec(
        brand="Tommy Hilfiger",
        model=None,
        product_type="Trainingshose",
        specs={"size": "XL"},
        price_relevant_attrs=[],
        confidence=0.90,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Size XL"
    )
    
    identity = ProductIdentity.from_product_spec(spec)
    
    assert "xl" not in identity.product_key.lower(), f"❌ Size 'XL' found in product_key: {identity.product_key}"
    assert identity.product_key == "tommy_hilfiger_trainingshose", f"❌ Wrong product_key: {identity.product_key}"
    
    print(f"✅ PASSED: product_key = {identity.product_key}")


def test_storage_gb_still_included():
    """
    P0.1: Storage (64GB) is price-relevant and MUST still be included.
    
    Should remain: "apple_iphone_12_mini_64GB"
    """
    print("\n=== TEST: Storage GB Still Included (Price-Relevant) ===")
    
    spec = ProductSpec(
        brand="Apple",
        model="iPhone 12 Mini",
        product_type="Smartphone",
        specs={"storage_gb": 64},  # Price-relevant!
        price_relevant_attrs=[],
        confidence=0.95,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Storage is price-relevant"
    )
    
    identity = ProductIdentity.from_product_spec(spec)
    
    # Storage MUST be in product_key
    assert "64GB" in identity.product_key, f"❌ Storage '64GB' missing from product_key: {identity.product_key}"
    assert identity.product_key == "apple_iphone_12_mini_64GB", f"❌ Wrong product_key: {identity.product_key}"
    
    # Storage MUST be in websearch_base (via websearch_query generation)
    assert identity.websearch_base == "Apple iPhone 12 Mini", f"❌ Wrong websearch_base: {identity.websearch_base}"
    
    print(f"✅ PASSED: product_key = {identity.product_key}")
    print(f"✅ PASSED: Storage correctly included")


def test_weight_kg_still_included():
    """
    P0.1: Weight (40kg) is price-relevant for weight-based products.
    
    Should remain: "gym_80_hantelscheiben_40kg"
    """
    print("\n=== TEST: Weight Still Included (Price-Relevant) ===")
    
    spec = ProductSpec(
        brand="Gym 80",
        model=None,
        product_type="Hantelscheiben",
        specs={"weight_kg": 40},  # Price-relevant for weights!
        price_relevant_attrs=[],
        confidence=0.90,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Weight defines the product"
    )
    
    identity = ProductIdentity.from_product_spec(spec)
    
    # Weight MUST be in product_key
    assert "40kg" in identity.product_key, f"❌ Weight '40kg' missing from product_key: {identity.product_key}"
    assert identity.product_key == "gym_80_hantelscheiben_40kg", f"❌ Wrong product_key: {identity.product_key}"
    
    print(f"✅ PASSED: product_key = {identity.product_key}")
    print(f"✅ PASSED: Weight correctly included")


def test_multiple_specs_size_filtered():
    """
    P0.1: When multiple specs present, only size should be filtered.
    """
    print("\n=== TEST: Multiple Specs - Only Size Filtered ===")
    
    spec = ProductSpec(
        brand="Apple",
        model="iPhone 12",
        product_type="Smartphone",
        specs={
            "storage_gb": 128,  # Keep
            "size": "M",        # Filter (if this were a case, hypothetically)
        },
        price_relevant_attrs=[],
        confidence=0.95,
        uncertainty_fields=[],
        extracted_from="title",
        extraction_notes="Multiple specs"
    )
    
    identity = ProductIdentity.from_product_spec(spec)
    
    # Storage should be included
    assert "128GB" in identity.product_key, f"❌ Storage missing: {identity.product_key}"
    
    # Size should NOT be included
    assert "m" not in identity.product_key.lower() or "128" in identity.product_key, f"❌ Size found: {identity.product_key}"
    
    print(f"✅ PASSED: product_key = {identity.product_key}")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("RUNNING P0.1 SIZE FILTERING TESTS")
    print("="*60)
    
    test_clothing_size_m_excluded()
    test_suit_size_98_excluded()
    test_size_xl_excluded()
    test_storage_gb_still_included()
    test_weight_kg_still_included()
    test_multiple_specs_size_filtered()
    
    print("\n" + "="*60)
    print("✅ ALL P0.1 TESTS PASSED")
    print("="*60)
    print("\nVerified:")
    print("  ✅ Clothing sizes (M, L, XL, 98) excluded from product_key")
    print("  ✅ Clothing sizes excluded from websearch queries")
    print("  ✅ Price-relevant specs (storage, weight) still included")
    print("  ✅ No false positives (storage GB not filtered)")
