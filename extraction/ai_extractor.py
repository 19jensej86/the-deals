"""
AI Extractor - Product Extraction with Claude/OpenAI
=====================================================
Extracts structured product data from listings using AI.

CRITICAL: Query-agnostic, zero hallucinations.
"""

import json
import re
import os
from typing import Optional, Dict, Any
from models.product_spec import ProductSpec
from models.extracted_product import ExtractedProduct
from models.bundle_types import BundleType
from extraction.ai_prompt import SYSTEM_PROMPT, generate_extraction_prompt


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


def _call_claude(prompt: str, max_tokens: int = 800) -> Optional[str]:
    """Call Claude API."""
    if not _claude_client:
        return None
    
    try:
        response = _claude_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": SYSTEM_PROMPT + "\n\n" + prompt}
            ]
        )
        return response.content[0].text
    except Exception as e:
        print(f"   ⚠️ Claude API error: {e}")
        return None


def _call_openai(prompt: str, max_tokens: int = 800) -> Optional[str]:
    """Call OpenAI API as fallback."""
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
        print(f"   ⚠️ OpenAI API error: {e}")
        return None


def _call_ai(prompt: str, max_tokens: int = 800) -> Optional[str]:
    """
    Call AI (Claude primary, OpenAI fallback).
    
    Args:
        prompt: User prompt
        max_tokens: Max response tokens
    
    Returns:
        AI response text or None
    """
    _init_ai_clients()
    
    # Try Claude first
    response = _call_claude(prompt, max_tokens)
    if response:
        return response
    
    # Fallback to OpenAI
    response = _call_openai(prompt, max_tokens)
    if response:
        return response
    
    return None


def extract_product_with_ai(
    listing_id: str,
    title: str,
    description: str = None
) -> ExtractedProduct:
    """
    Extracts product information from listing using AI.
    
    IMPORTANT: AI does NOT see search query!
    
    Args:
        listing_id: Unique listing identifier
        title: Listing title
        description: Optional description (first 300 chars used)
    
    Returns:
        ExtractedProduct with structured data
    """
    
    # Generate prompt (NO query information!)
    user_prompt = generate_extraction_prompt(title, description)
    
    # Call AI
    raw_response = _call_ai(user_prompt, max_tokens=800)
    
    if not raw_response:
        # AI call failed - return empty with low confidence
        return ExtractedProduct(
            listing_id=listing_id,
            original_title=title,
            products=[],
            quantities=[],
            bundle_type=BundleType.UNKNOWN,
            bundle_confidence=0.0,
            overall_confidence=0.0,
            can_price=False,
            needs_detail_scraping=True,
            needs_vision=False,
            skip_reason="ai_extraction_failed",
            extraction_method="ai_structured",
            ai_cost_usd=0.0
        )
    
    # Parse JSON response
    try:
        json_match = re.search(r'\{[\s\S]*\}', raw_response)
        if not json_match:
            raise ValueError("No JSON found in response")
        
        data = json.loads(json_match.group(0))
        
        # Extract ProductSpec
        product_spec = ProductSpec(
            brand=data.get("brand"),
            model=data.get("model"),
            product_type=data.get("product_type", "Unknown"),
            final_search_name=data.get("final_search_name"),
            category=data.get("category"),
            expected_resale_rate=data.get("expected_resale_rate"),
            specs=data.get("specs", {}),
            price_relevant_attrs=data.get("price_relevant_attrs", []),
            confidence=data.get("confidence", 0.0),
            uncertainty_fields=data.get("uncertainty_fields", []),
            extracted_from="title",
            extraction_notes=data.get("extraction_notes", "")
        )
        
        # Parse bundle type
        bundle_type_str = data.get("bundle_type", "single_product")
        try:
            bundle_type = BundleType(bundle_type_str)
        except ValueError:
            bundle_type = BundleType.UNKNOWN
        
        # v12: Extract is_accessory_only flag (combined AI call for cost savings)
        is_accessory_only = data.get("is_accessory_only", False)
        
        # Determine if we have valid products
        quantity = data.get("quantity", 1)
        products = []
        quantities = []
        
        # Only add product if confidence is reasonable
        if product_spec.confidence >= 0.5 and product_spec.product_type:
            products = [product_spec]
            quantities = [quantity if quantity else 1]
        
        # Overall confidence
        overall_confidence = product_spec.confidence
        
        # Can we price this?
        can_price = (
            overall_confidence >= 0.6 and
            bundle_type != BundleType.UNKNOWN and
            len(products) > 0 and
            not is_accessory_only  # v12: Skip accessories
        )
        
        # Do we need detail scraping?
        needs_detail = data.get("needs_detail", False) or overall_confidence < 0.7
        
        # Skip reason includes accessory detection
        skip_reason = None
        if is_accessory_only:
            skip_reason = "accessory_only"
        elif not can_price and not needs_detail:
            skip_reason = "confidence_too_low"
        
        # Calculate AI cost (rough estimate)
        # Claude Haiku: ~$0.25 per 1M input tokens, ~$1.25 per 1M output tokens
        input_tokens = len(user_prompt) / 4  # Rough estimate
        output_tokens = len(raw_response) / 4
        ai_cost = (input_tokens * 0.25 / 1_000_000) + (output_tokens * 1.25 / 1_000_000)
        
        return ExtractedProduct(
            listing_id=listing_id,
            original_title=title,
            products=products,
            quantities=quantities,
            bundle_type=bundle_type,
            bundle_confidence=overall_confidence,
            overall_confidence=overall_confidence,
            can_price=can_price,
            needs_detail_scraping=needs_detail,
            needs_vision=overall_confidence < 0.5,
            skip_reason=skip_reason,
            is_accessory_only=is_accessory_only,  # v12: Store AI's accessory detection
            extraction_method="ai_structured",
            ai_cost_usd=ai_cost
        )
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        # Parsing failed - return empty with low confidence
        print(f"   ⚠️ Failed to parse AI response: {e}")
        return ExtractedProduct(
            listing_id=listing_id,
            original_title=title,
            products=[],
            quantities=[],
            bundle_type=BundleType.UNKNOWN,
            bundle_confidence=0.0,
            overall_confidence=0.0,
            can_price=False,
            needs_detail_scraping=True,
            needs_vision=False,
            skip_reason="ai_response_parse_error",
            extraction_method="ai_structured",
            ai_cost_usd=0.0
        )
