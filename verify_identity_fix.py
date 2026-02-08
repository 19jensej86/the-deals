"""
Quick verification script - shows identity generation results.
Run this to verify the corruption fix works.
"""

from models.product_identity import ProductIdentity
from models.product_spec import ProductSpec


def verify_fix():
    print("=" * 70)
    print("IDENTITY CORRUPTION FIX - VERIFICATION")
    print("=" * 70)
    print()
    
    test_cases = [
        {
            "name": "Apple iPhone 12 mini 128GB",
            "spec": ProductSpec(
                brand="Apple",
                model="iPhone 12 mini",
                product_type="smartphone",
                specs={"storage_gb": "128"}
            ),
            "must_contain": "12",
            "must_not_contain": "iphone 1 "
        },
        {
            "name": "iPhone 12 mini (no brand)",
            "spec": ProductSpec(
                brand=None,
                model="iPhone 12 mini",
                product_type="smartphone",
                specs={"storage_gb": "128"}
            ),
            "must_contain": "12",
            "must_not_contain": "iphone 1 "
        },
        {
            "name": "Sony WH-1000XM4",
            "spec": ProductSpec(
                brand="Sony",
                model="WH-1000XM4",
                product_type="headphones",
                specs={}
            ),
            "must_contain": "1000",
            "must_not_contain": "wh-100xm4"
        },
        {
            "name": "Samsung Galaxy Watch 4",
            "spec": ProductSpec(
                brand="Samsung",
                model="Galaxy Watch 4",
                product_type="smartwatch",
                specs={}
            ),
            "must_contain": "4",
            "must_not_contain": None
        }
    ]
    
    all_passed = True
    
    for test in test_cases:
        print(f"Test: {test['name']}")
        identity = ProductIdentity.from_product_spec(test['spec'])
        
        # For generation tests, modify websearch_base
        if "AirPods" in test['name'] and "generation" in test['name'].lower():
            identity.websearch_base = test['name']
        
        canonical_key = identity.get_canonical_identity_key()
        
        print(f"  product_key:    {identity.product_key}")
        print(f"  websearch_base: {identity.websearch_base}")
        print(f"  canonical_key:  {canonical_key}")
        
        # Check must_contain
        if test['must_contain'] and test['must_contain'] not in canonical_key:
            print(f"  ❌ FAIL: Missing '{test['must_contain']}'")
            all_passed = False
        elif test['must_contain']:
            print(f"  ✅ Contains '{test['must_contain']}'")
        
        # Check must_not_contain
        if test['must_not_contain'] and test['must_not_contain'] in canonical_key:
            print(f"  ❌ FAIL: Contains forbidden '{test['must_not_contain']}'")
            all_passed = False
        
        print()
    
    # Test generation normalization
    print("Test: AirPods Pro (2nd generation)")
    spec = ProductSpec(brand="Apple", model="AirPods Pro", product_type="earbuds", specs={})
    identity = ProductIdentity.from_product_spec(spec)
    identity.websearch_base = "Apple AirPods Pro (2nd generation)"
    canonical_key = identity.get_canonical_identity_key()
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key:  {canonical_key}")
    if "gen_2" in canonical_key:
        print(f"  ✅ Generation normalized to 'gen_2'")
    else:
        print(f"  ❌ FAIL: Generation not normalized")
        all_passed = False
    print()
    
    print("Test: AirPods (2. Generation)")
    identity.websearch_base = "Apple AirPods (2. Generation)"
    canonical_key = identity.get_canonical_identity_key()
    print(f"  websearch_base: {identity.websearch_base}")
    print(f"  canonical_key:  {canonical_key}")
    if "gen_2" in canonical_key:
        print(f"  ✅ Generation normalized to 'gen_2'")
    else:
        print(f"  ❌ FAIL: Generation not normalized")
        all_passed = False
    print()
    
    print("=" * 70)
    if all_passed:
        print("✅ ALL CHECKS PASSED - Identity generation is safe")
    else:
        print("❌ SOME CHECKS FAILED - Review output above")
    print("=" * 70)
    
    return all_passed


if __name__ == "__main__":
    verify_fix()
