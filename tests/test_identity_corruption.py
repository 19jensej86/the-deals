"""
Unit tests for identity generation - prevents model number corruption.

CRITICAL TEST CASES:
- iPhone 12 must NOT become iPhone 1
- WH-1000XM4 must NOT become WH-100XM4
- Generation expressions should normalize correctly
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product_identity import ProductIdentity
from models.product_spec import ProductSpec


def test_iphone_12_not_corrupted():
    """iPhone 12 mini must preserve the '12' in identity key."""
    spec = ProductSpec(
        brand="Apple",
        model="iPhone 12 mini",
        product_type="smartphone",
        specs={"storage_gb": "128"}
    )
    identity = ProductIdentity.from_product_spec(spec)
    canonical_key = identity.get_canonical_identity_key()
    
    print(f"Test: iPhone 12 mini")
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key: {canonical_key}")
    
    # MUST contain "12"
    assert "12" in canonical_key, f"FAIL: '12' missing from '{canonical_key}'"
    # MUST NOT contain "1 " (corrupted)
    assert "iphone 1 " not in canonical_key, f"FAIL: Corrupted to 'iphone 1' in '{canonical_key}'"
    print("  ✅ PASS: '12' preserved\n")


def test_iphone_12_no_brand():
    """iPhone 12 mini (without brand) must preserve the '12'."""
    spec = ProductSpec(
        brand=None,
        model="iPhone 12 mini",
        product_type="smartphone",
        specs={"storage_gb": "128"}
    )
    identity = ProductIdentity.from_product_spec(spec)
    canonical_key = identity.get_canonical_identity_key()
    
    print(f"Test: iPhone 12 mini (no brand)")
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key: {canonical_key}")
    
    # MUST contain "12"
    assert "12" in canonical_key, f"FAIL: '12' missing from '{canonical_key}'"
    print("  ✅ PASS: '12' preserved\n")


def test_airpods_pro_2nd_generation():
    """AirPods Pro (2nd generation) should normalize generation correctly."""
    spec = ProductSpec(
        brand="Apple",
        model="AirPods Pro",
        product_type="earbuds",
        specs={}
    )
    identity = ProductIdentity.from_product_spec(spec)
    
    # Test with generation in websearch_base
    identity.websearch_base = "Apple AirPods Pro (2nd generation)"
    canonical_key = identity.get_canonical_identity_key()
    
    print(f"Test: AirPods Pro (2nd generation)")
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key: {canonical_key}")
    
    # Should normalize to gen_2
    assert "gen_2" in canonical_key, f"FAIL: Generation not normalized in '{canonical_key}'"
    # Should NOT have standalone "2"
    assert " 2 " not in canonical_key or "gen_2" in canonical_key, f"FAIL: Unexpected '2' in '{canonical_key}'"
    print("  ✅ PASS: Generation normalized to gen_2\n")


def test_sony_wh1000xm4_not_corrupted():
    """Sony WH-1000XM4 must preserve '1000' in model number."""
    spec = ProductSpec(
        brand="Sony",
        model="WH-1000XM4",
        product_type="headphones",
        specs={}
    )
    identity = ProductIdentity.from_product_spec(spec)
    canonical_key = identity.get_canonical_identity_key()
    
    print(f"Test: Sony WH-1000XM4")
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key: {canonical_key}")
    
    # MUST contain "1000"
    assert "1000" in canonical_key, f"FAIL: '1000' missing from '{canonical_key}'"
    # MUST NOT be corrupted to "100"
    assert "wh-100xm4" not in canonical_key, f"FAIL: Corrupted to 'wh-100xm4' in '{canonical_key}'"
    print("  ✅ PASS: '1000' preserved\n")


def test_galaxy_watch_4():
    """Samsung Galaxy Watch 4 must preserve '4'."""
    spec = ProductSpec(
        brand="Samsung",
        model="Galaxy Watch 4",
        product_type="smartwatch",
        specs={}
    )
    identity = ProductIdentity.from_product_spec(spec)
    canonical_key = identity.get_canonical_identity_key()
    
    print(f"Test: Samsung Galaxy Watch 4")
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key: {canonical_key}")
    
    # MUST contain "4"
    assert "4" in canonical_key, f"FAIL: '4' missing from '{canonical_key}'"
    print("  ✅ PASS: '4' preserved\n")


def test_airpods_2_generation_variant():
    """AirPods (2. Generation) should normalize correctly."""
    spec = ProductSpec(
        brand="Apple",
        model="AirPods",
        product_type="earbuds",
        specs={}
    )
    identity = ProductIdentity.from_product_spec(spec)
    
    # Test German format
    identity.websearch_base = "Apple AirPods (2. Generation)"
    canonical_key = identity.get_canonical_identity_key()
    
    print(f"Test: AirPods (2. Generation)")
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key: {canonical_key}")
    
    # Should normalize to gen_2
    assert "gen_2" in canonical_key, f"FAIL: Generation not normalized in '{canonical_key}'"
    print("  ✅ PASS: German generation format normalized\n")


if __name__ == "__main__":
    print("=" * 70)
    print("IDENTITY CORRUPTION TESTS - Emergency Fix Verification")
    print("=" * 70)
    print()
    
    try:
        test_iphone_12_not_corrupted()
        test_iphone_12_no_brand()
        test_airpods_pro_2nd_generation()
        test_sony_wh1000xm4_not_corrupted()
        test_galaxy_watch_4()
        test_airpods_2_generation_variant()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED - Identity generation is safe")
        print("=" * 70)
    except AssertionError as e:
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        sys.exit(1)
