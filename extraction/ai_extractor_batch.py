"""
AI Extractor - BATCH Product Extraction with Claude/OpenAI
===========================================================
Extracts structured product data from MULTIPLE listings in ONE AI call.

OPTIMIZATION: 79% cost reduction vs individual calls
- Old: 31 listings × $0.003 = $0.096
- New: 1 batch call = $0.020
"""

import json
import re
import os
from typing import Optional, Dict, Any, List
from models.product_spec import ProductSpec
from models.extracted_product import ExtractedProduct
from models.bundle_types import BundleType
from extraction.ai_prompt import SYSTEM_PROMPT


# AI Client initialization
_claude_client = None
_openai_client = None


def _init_ai_clients():
    """Initialize AI clients (Claude primary, OpenAI fallback)."""
    global _claude_client, _openai_client
    
    # Try Claude first
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key and not _claude_client:
        try:
            import anthropic
            _claude_client = anthropic.Anthropic(api_key=anthropic_key)
        except ImportError:
            pass
    
    # OpenAI as fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key and not _openai_client:
        try:
            import openai
            _openai_client = openai.OpenAI(api_key=openai_key)
        except ImportError:
            pass


def _call_claude_batch(prompt: str, max_tokens: int = 4000) -> Optional[str]:
    """Call Claude API for batch extraction."""
    if not _claude_client:
        return None
    
    try:
        response = _claude_client.messages.create(
            model="claude-3-5-haiku-20250514",  # Haiku 4.5
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": SYSTEM_PROMPT + "\n\n" + prompt}
            ]
        )
        return response.content[0].text
    except Exception as e:
        print(f"   ⚠️ Claude batch API error: {e}")
        return None


def _call_openai_batch(prompt: str, max_tokens: int = 4000) -> Optional[str]:
    """Call OpenAI API as fallback for batch extraction."""
    if not _openai_client:
        return None
    
    try:
        response = _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"   ⚠️ OpenAI batch API error: {e}")
        return None


def extract_products_batch(
    listings: List[Dict[str, Any]]
) -> Dict[str, ExtractedProduct]:
    """
    Extracts product information from MULTIPLE listings in ONE AI call.
    
    COST OPTIMIZATION:
    - Old: N listings × $0.003 = $0.003N
    - New: 1 call = ~$0.020 (regardless of N)
    - Savings: ~79% for N=31
    
    Args:
        listings: List of dicts with keys: listing_id, title, description (optional)
    
    Returns:
        Dict mapping listing_id → ExtractedProduct
    """
    if not listings:
        return {}
    
    _init_ai_clients()
    
    # Build batch prompt
    listings_text = []
    for idx, listing in enumerate(listings, 1):
        title = listing.get("title", "")
        desc = listing.get("description", "")
        if desc:
            desc = desc[:200]  # Limit description length
        
        listings_text.append(f"""
{idx}. ID: {listing.get('listing_id')}
   Title: {title}
   Description: {desc if desc else "(none)"}
""")
    
    batch_prompt = f"""Extract product information from these {len(listings)} listings.

LISTINGS:
{"".join(listings_text)}

For EACH listing, extract:
- brand: Brand name (or null)
- model: Model name/number (or null)
- product_type: Type of product (e.g., "Smartwatch", "Headphones")
- category: Category (e.g., "electronics", "fitness", "clothing")
- quantity: Number of items (default: 1)
- confidence: 0.0-1.0 (how confident are you?)
- is_accessory_only: true if ONLY accessories (e.g., "Armband für Apple Watch")
- bundle_type: "single_product", "homogeneous_bundle", "heterogeneous_bundle", or "unknown"
- needs_detail: true if title is unclear and needs detail page scraping

CRITICAL RULES:
1. NEVER invent information not in the title/description
2. If uncertain, use null and set confidence < 0.7
3. Accessories ONLY (no main product) → is_accessory_only: true
4. Bundle = multiple items in one listing

Respond ONLY as JSON array (one object per listing, in same order):
[
  {{
    "listing_id": "...",
    "brand": "Apple",
    "model": "Watch Ultra",
    "product_type": "Smartwatch",
    "category": "electronics",
    "quantity": 1,
    "confidence": 0.85,
    "is_accessory_only": false,
    "bundle_type": "single_product",
    "needs_detail": false
  }},
  {{
    "listing_id": "...",
    "brand": null,
    "model": null,
    "product_type": "Armband",
    "category": "accessories",
    "quantity": 1,
    "confidence": 0.9,
    "is_accessory_only": true,
    "bundle_type": "single_product",
    "needs_detail": false
  }},
  ...
]"""
    
    # Call AI
    raw_response = _call_claude_batch(batch_prompt, max_tokens=4000)
    if not raw_response:
        raw_response = _call_openai_batch(batch_prompt, max_tokens=4000)
    
    if not raw_response:
        print("   ❌ Batch extraction failed - falling back to empty results")
        return {
            listing.get("listing_id"): _create_failed_extraction(listing)
            for listing in listings
        }
    
    # Parse JSON array response
    try:
        json_match = re.search(r'\[[\s\S]*\]', raw_response)
        if not json_match:
            raise ValueError("No JSON array found in response")
        
        data_array = json.loads(json_match.group(0))
        
        # Map results to listing IDs
        results = {}
        for data in data_array:
            listing_id = data.get("listing_id")
            if not listing_id:
                continue
            
            # Find original listing for title
            original = next((l for l in listings if l.get("listing_id") == listing_id), None)
            if not original:
                continue
            
            # Build ExtractedProduct
            product_spec = ProductSpec(
                brand=data.get("brand"),
                model=data.get("model"),
                product_type=data.get("product_type", "Unknown"),
                final_search_name=f"{data.get('brand', '')} {data.get('model', '')}".strip() or None,
                category=data.get("category"),
                expected_resale_rate=None,
                specs={},
                price_relevant_attrs=[],
                confidence=data.get("confidence", 0.0),
                uncertainty_fields=[],
                extracted_from="title",
                extraction_notes=""
            )
            
            # Parse bundle type
            bundle_type_str = data.get("bundle_type", "single_product")
            try:
                bundle_type = BundleType(bundle_type_str)
            except ValueError:
                bundle_type = BundleType.UNKNOWN
            
            is_accessory_only = data.get("is_accessory_only", False)
            quantity = data.get("quantity", 1)
            
            products = []
            quantities = []
            if product_spec.confidence >= 0.5 and product_spec.product_type:
                products = [product_spec]
                quantities = [quantity if quantity else 1]
            
            overall_confidence = product_spec.confidence
            
            can_price = (
                overall_confidence >= 0.6 and
                bundle_type != BundleType.UNKNOWN and
                len(products) > 0 and
                not is_accessory_only
            )
            
            needs_detail = data.get("needs_detail", False) or overall_confidence < 0.7
            
            skip_reason = None
            if is_accessory_only:
                skip_reason = "accessory_only"
            elif not can_price and not needs_detail:
                skip_reason = "confidence_too_low"
            
            # Estimate cost: ~$0.020 total / N listings
            ai_cost = 0.020 / len(listings)
            
            results[listing_id] = ExtractedProduct(
                listing_id=listing_id,
                original_title=original.get("title", ""),
                products=products,
                quantities=quantities,
                bundle_type=bundle_type,
                bundle_confidence=overall_confidence,
                overall_confidence=overall_confidence,
                can_price=can_price,
                needs_detail_scraping=needs_detail,
                needs_vision=overall_confidence < 0.5,
                skip_reason=skip_reason,
                is_accessory_only=is_accessory_only,
                extraction_method="ai_batch",
                ai_cost_usd=ai_cost
            )
        
        # Fill in any missing listings with failed extractions
        for listing in listings:
            listing_id = listing.get("listing_id")
            if listing_id not in results:
                results[listing_id] = _create_failed_extraction(listing)
        
        return results
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        error_type = type(e).__name__
        print(f"   ❌ BATCH EXTRACTION FAILED: {error_type} - {str(e)[:100]}")
        return {
            listing.get("listing_id"): _create_failed_extraction(listing)
            for listing in listings
        }


def _create_failed_extraction(listing: Dict[str, Any]) -> ExtractedProduct:
    """Create a failed extraction result."""
    return ExtractedProduct(
        listing_id=listing.get("listing_id", ""),
        original_title=listing.get("title", ""),
        products=[],
        quantities=[],
        bundle_type=BundleType.UNKNOWN,
        bundle_confidence=0.0,
        overall_confidence=0.0,
        can_price=False,
        extraction_status="FAILED",
        failure_reason="batch_extraction_failed",
        needs_detail_scraping=False,
        needs_vision=False,
        skip_reason="extraction_failed",
        extraction_method="ai_batch",
        ai_cost_usd=0.0
    )
