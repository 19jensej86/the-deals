"""
AI Filter & Evaluation - v7.3.5 (Optimized Edition)
====================================================
MAJOR CHANGES in v7.3.5:
- Bundle component web search with caching
- Cache statistics tracking
- Optimized logging

MAJOR CHANGES in v7.0:

1. CLAUDE PRIMARY - OpenAI fallback
   - All AI calls use Claude (Haiku for speed, Sonnet for web search)
   - Automatic fallback to OpenAI if Claude unavailable

2. REAL WEB SEARCH (THE GAME CHANGER!)
   - Uses Claude Sonnet + web_search tool
   - Actually searches Digitec, Galaxus, etc.
   - 85-90% success rate (vs 16% with GPT memory)
   - Cached for 60 days

3. All v6.8 features preserved:
   - Weight-based pricing for fitness equipment
   - Bundle detection with vision
   - Market-based pricing from Ricardo auctions
   - Variant clustering
   - Deal score calculation

PRICING PHILOSOPHY (unchanged):
==============================
1. AUCTION DATA > AI ESTIMATES (always)
2. More bids = more trust (20+ bids = fully trusted)
3. Buy-now ceiling is a CEILING, not a floor
4. Each variant has its own reference price
5. Used items max 70% of THEIR new price
6. Premium brands/materials = higher new prices
7. Fitness equipment = always check visually for quantity
"""

import os
import random
import datetime
import json
import re
import statistics
import base64
from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal

from dotenv import load_dotenv

# ==============================================================================
# PRICE SOURCE CONSTANTS (Schema-Valid Enum)
# ==============================================================================
# These MUST match the CHECK constraint in db_pg.py LISTINGS_V11_SCHEMA
# Any other value will cause: psycopg2.errors.CheckViolation

PRICE_SOURCE_WEB_MEDIAN = "web_median"
PRICE_SOURCE_WEB_SINGLE = "web_single"
PRICE_SOURCE_WEB_QTY_ADJUSTED = "web_median_qty_adjusted"
PRICE_SOURCE_AI_ESTIMATE = "ai_estimate"
PRICE_SOURCE_QUERY_BASELINE = "query_baseline"
PRICE_SOURCE_BUY_NOW_FALLBACK = "buy_now_fallback"
PRICE_SOURCE_BUNDLE_AGGREGATE = "bundle_aggregate"
PRICE_SOURCE_MARKET_AUCTION = "market_auction"
PRICE_SOURCE_NO_PRICE = "no_price"

# Internal-only constants (not in schema, used for logic flow)
PRICE_SOURCE_UNKNOWN = "unknown"  # Temporary state, must be replaced before DB insert

# Valid set for validation (schema-enforced values only)
VALID_PRICE_SOURCES = {
    PRICE_SOURCE_WEB_MEDIAN,
    PRICE_SOURCE_WEB_SINGLE,
    PRICE_SOURCE_WEB_QTY_ADJUSTED,
    PRICE_SOURCE_AI_ESTIMATE,
    PRICE_SOURCE_QUERY_BASELINE,
    PRICE_SOURCE_BUY_NOW_FALLBACK,
    PRICE_SOURCE_BUNDLE_AGGREGATE,
    PRICE_SOURCE_MARKET_AUCTION,
    PRICE_SOURCE_NO_PRICE,
}

load_dotenv()

# v7.3.5: Import cache statistics tracking
try:
    from utils_logging import get_cache_stats
except ImportError:
    # Fallback if utils_logging not available
    class DummyCacheStats:
        def record_web_price_hit(self): pass
        def record_web_price_miss(self): pass
        def record_variant_hit(self): pass
        def record_variant_miss(self): pass
    def get_cache_stats():
        return DummyCacheStats()


# ==============================================================================
# v7.0: CLIENT INITIALIZATION - Claude PRIMARY, OpenAI fallback
# ==============================================================================

_claude_client = None
_openai_client = None
_provider = "claude"
_config = None  # Will be set by init_ai_filter()

def _init_clients():
    """Initialize AI clients based on available API keys."""
    global _claude_client, _openai_client, _provider
    
    # Try Claude first
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            _claude_client = anthropic.Anthropic(api_key=anthropic_key)
            _provider = "claude"
            print("🤖 AI Filter: Claude initialized ✅")
        except ImportError:
            print("⚠️ anthropic package not installed")
        except Exception as e:
            print(f"⚠️ Claude init failed: {e}")
    
    # Also init OpenAI as fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=openai_key)
            if _claude_client is None:
                _provider = "openai"
                print("🤖 AI Filter: Using OpenAI (fallback)")
            else:
                print("🤖 AI Filter: OpenAI available as fallback")
        except ImportError:
            print("⚠️ openai package not installed")
    
    if _claude_client is None and _openai_client is None:
        print("❌ No AI client available! Set ANTHROPIC_API_KEY or OPENAI_API_KEY")


# Initialize on module load
_init_clients()


# ==============================================================================
# CONSTANTS
# ==============================================================================

# v7.3.3: CORRECTED COSTS based on ACTUAL billing
# UPDATED 2026-01-20: Haiku 3.5 → Haiku 4.5 (4x price increase)
# Web search with Sonnet includes large search result tokens!
COST_CLAUDE_HAIKU = 0.012          # Haiku 4.5: ~3k tokens × $4/1M = $0.012 (was $0.003)
COST_CLAUDE_SONNET = 0.01          # Sonnet 4: ~3k tokens × $3/1M = $0.01  
COST_CLAUDE_WEB_SEARCH = 0.35      # Sonnet 4 + web: ~$0.35 per batch (includes search results)
COST_OPENAI_TEXT = 0.001
COST_VISION = 0.007

# v7.3.4: Adjusted limits for SINGLE web search strategy
# With single batch strategy: 1 search = all products = $0.35
DAILY_COST_LIMIT = 3.00            # ~8 full runs per day
DAILY_VISION_LIMIT = 50
DAILY_WEB_SEARCH_LIMIT = 5         # Max 5 single searches = ~$1.75

WEB_SEARCH_COUNT_TODAY: int = 0
WEB_SEARCH_ENABLED: bool = True  # v7.3.2: Toggle via config.yaml to save costs
WEB_PRICE_CACHE_FILE = "web_price_cache.json"
WEB_PRICE_CACHE_DAYS = 60
_web_price_cache: Dict[str, Dict] = {}

RICARDO_FEE_PERCENT = 0.10
SHIPPING_COST_CHF = 0.0
MIN_PROFIT_THRESHOLD = 20.0

BUNDLE_ENABLED = True
BUNDLE_DISCOUNT_PERCENT = 0.10
BUNDLE_MIN_COMPONENT_VALUE = 10.0
MAX_COMPONENT_PRICE = 300.0  # Max realistic price per component (CHF)
BUNDLE_USE_VISION = True

CACHE_ENABLED = True
VARIANT_CACHE_DAYS = 30
COMPONENT_CACHE_DAYS = 30
CLUSTER_CACHE_DAYS = 7
CATEGORY_THRESHOLD_CACHE_DAYS = 365  # Category behavior is stable year-over-year

RUN_COST_USD: float = 0.0
DAY_COST_FILE = "ai_cost_day.txt"

VARIANT_CACHE_FILE = "variant_cache.json"
COMPONENT_CACHE_FILE = "component_cache.json"
CLUSTER_CACHE_FILE = "variant_cluster_cache.json"
CATEGORY_THRESHOLD_CACHE_FILE = "category_threshold_cache.json"

USE_VISION = True
VISION_RATE = 0.10
DEFAULT_CAR_MODEL = "VW Touran"

MIN_SAMPLES_FOR_MARKET_PRICE = 2
MIN_HOURS_FOR_PRICE_TRUST = 6
MIN_BIDS_FOR_PRICE_TRUST = 8

UNREALISTIC_PRICE_RATIO = 0.20
HIGH_DEMAND_BID_COUNT = 12
MODERATE_BID_COUNT = 5

HIGH_ACTIVITY_BID_THRESHOLD = 10
VERY_HIGH_ACTIVITY_BID_THRESHOLD = 20
HIGH_ACTIVITY_MIN_PRICE_RATIO = 0.15

MAX_RESALE_PERCENT_OF_NEW = 0.70
MAX_BUNDLE_RESALE_PERCENT_OF_NEW = 0.85

COMPONENT_MARKET_TRUST_MULTIPLIER = 5.0

# ==============================================================================
# v7.0: UNIFIED AI CALL WRAPPER
# ==============================================================================

def _call_claude(
    prompt: str,
    max_tokens: int = 500,
    model: str = None,
    use_web_search: bool = False,
    image_url: str = None,
    step: str = "unknown",
) -> Optional[str]:
    """
    Call Claude API with optional web search or vision.
    
    Args:
        prompt: The prompt text
        max_tokens: Maximum response tokens
        model: Override model (default: MODEL_FAST)
        use_web_search: Enable web search tool
        image_url: Optional image URL for vision
        step: Pipeline step name for logging
    
    Returns:
        Response text or None on error
    """
    if not _claude_client:
        return None
    
    # Select model from config
    if not _config:
        raise RuntimeError("AI Filter not initialized. Call init_ai_filter(cfg) first.")
    
    if use_web_search:
        selected_model = _config.ai.claude_model_web
    else:
        selected_model = model or _config.ai.claude_model_fast
    
    # AI_CALL_DECISION: Log before making AI call
    runtime_mode = getattr(_config.runtime, 'mode', 'unknown')
    call_type = "vision" if image_url else ("websearch" if use_web_search else "text")
    print(f"\nAI_CALL_DECISION:")
    print(f"  step: {step}")
    print(f"  runtime_mode: {runtime_mode}")
    print(f"  model: {selected_model}")
    print(f"  call_type: {call_type}")
    print(f"  allowed: true")
    print(f"  reason: AI_ENABLED")
    
    try:
        # Build messages
        if image_url:
            # Vision request
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {"type": "url", "url": image_url}}
                ]
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        # Build request kwargs
        kwargs = {
            "model": selected_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        
        # Add web search tool if requested
        if use_web_search:
            kwargs["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search"
            }]
        
        response = _claude_client.messages.create(**kwargs)
        
        # Extract text from response (handle multiple content blocks)
        result_parts = []
        for block in response.content:
            if hasattr(block, 'text'):
                result_parts.append(block.text)
        
        return "\n".join(result_parts) if result_parts else None
        
    except Exception as e:
        error_str = str(e)
        
        # AI_FAILURE: Structured error logging
        runtime_mode = getattr(_config.runtime, 'mode', 'unknown')
        error_type = "rate_limit" if ("429" in error_str or "rate_limit" in error_str.lower()) else "api_error"
        
        print(f"\nAI_FAILURE:")
        print(f"  step: {step}")
        print(f"  model: {selected_model}")
        print(f"  runtime_mode: {runtime_mode}")
        print(f"  error_type: {error_type}")
        print(f"  error_message: {str(e)[:100]}")
        
        # Re-raise 429 rate limit errors so retry logic can handle them
        if error_type == "rate_limit":
            print(f"  action_taken: re-raise (retry logic will handle)")
            raise  # Let caller handle rate limits
        
        print(f"  action_taken: return_none (caller fallback)")
        return None


def _call_openai(
    prompt: str,
    max_tokens: int = 500,
    model: str = None,
    image_url: str = None,
    step: str = "unknown",
) -> Optional[str]:
    """Call OpenAI API (fallback)."""
    if not _openai_client:
        return None
    
    if not _config:
        raise RuntimeError("AI Filter not initialized. Call init_ai_filter(cfg) first.")
    
    selected_model = model or _config.ai.openai_model
    
    # AI_CALL_DECISION: Log before making AI call
    runtime_mode = getattr(_config.runtime, 'mode', 'unknown')
    call_type = "vision" if image_url else "text"
    print(f"\nAI_CALL_DECISION:")
    print(f"  step: {step}")
    print(f"  runtime_mode: {runtime_mode}")
    print(f"  model: {selected_model}")
    print(f"  call_type: {call_type}")
    print(f"  allowed: true")
    print(f"  reason: OPENAI_FALLBACK")
    
    try:
        if image_url:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        response = _openai_client.chat.completions.create(
            model=selected_model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        # AI_FAILURE: Structured error logging
        runtime_mode = getattr(_config.runtime, 'mode', 'unknown')
        print(f"\nAI_FAILURE:")
        print(f"  step: {step}")
        print(f"  model: {selected_model}")
        print(f"  runtime_mode: {runtime_mode}")
        print(f"  error_type: api_error")
        print(f"  error_message: {str(e)[:100]}")
        print(f"  action_taken: return_none")
        return None


def call_ai(
    prompt: str,
    max_tokens: int = 500,
    use_web_search: bool = False,
    image_url: str = None,
) -> Optional[str]:
    """
    Unified AI call with automatic provider selection.
    
    Uses Claude if available, falls back to OpenAI.
    Web search only available with Claude.
    """
    # Try Claude first
    if _provider == "claude" and _claude_client:
        result = _call_claude(
            prompt=prompt,
            max_tokens=max_tokens,
            use_web_search=use_web_search,
            image_url=image_url,
        )
        if result:
            return result
    
    # Fallback to OpenAI (no web search)
    if _openai_client:
        if use_web_search:
            print("   ⚠️ Web search not available with OpenAI fallback")
        return _call_openai(
            prompt=prompt,
            max_tokens=max_tokens,
            image_url=image_url,
        )
    
    return None


# ==============================================================================
# v11: EXPLICIT QUANTITY PARSING FROM SHOP SNIPPETS
# ==============================================================================

def parse_quantity_from_snippet(snippet: str) -> Dict[str, Any]:
    """
    v11: Parse quantity and weight from shop text snippets.
    
    Patterns recognized:
    - "2 × 5 kg" → qty=2, weight=5
    - "2x5kg" → qty=2, weight=5
    - "Set 4 × 10 kg" → qty=4, weight=10
    - "Paar 15kg" → qty=2, weight=15
    - "2er Set 5kg" → qty=2, weight=5
    
    Returns:
        Dict with quantity_in_offer, unit_weight_kg, pattern_matched
    
    RULE: Only return values if EXPLICITLY found in text. No assumptions!
    """
    import re
    
    if not snippet:
        return {"quantity_in_offer": None, "unit_weight_kg": None, "pattern_matched": None}
    
    snippet_lower = snippet.lower().strip()
    result = {"quantity_in_offer": None, "unit_weight_kg": None, "pattern_matched": None}
    
    # Pattern 1: "N × M kg" or "Nx M kg" (e.g., "2 × 5 kg", "4x10kg")
    qty_weight_match = re.search(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', snippet_lower)
    if qty_weight_match:
        result["quantity_in_offer"] = int(qty_weight_match.group(1))
        result["unit_weight_kg"] = float(qty_weight_match.group(2).replace(',', '.'))
        result["pattern_matched"] = qty_weight_match.group(0)
        return result
    
    # Pattern 2: "Paar" = 2 pieces (explicit)
    if re.search(r'\bpaar\b', snippet_lower):
        weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', snippet_lower)
        if weight_match:
            result["quantity_in_offer"] = 2
            result["unit_weight_kg"] = float(weight_match.group(1).replace(',', '.'))
            result["pattern_matched"] = f"paar + {weight_match.group(0)}"
            return result
    
    # Pattern 3: "2er Set" or "4er Pack" (German quantity indicators)
    set_match = re.search(r'(\d+)er[\s-]*(set|pack|kit)', snippet_lower)
    if set_match:
        weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', snippet_lower)
        if weight_match:
            result["quantity_in_offer"] = int(set_match.group(1))
            result["unit_weight_kg"] = float(weight_match.group(1).replace(',', '.'))
            result["pattern_matched"] = f"{set_match.group(0)} + {weight_match.group(0)}"
            return result
    
    # Pattern 4: "Set of N" or "Pack of N" (English)
    set_of_match = re.search(r'(set|pack)\s+of\s+(\d+)', snippet_lower)
    if set_of_match:
        weight_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', snippet_lower)
        if weight_match:
            result["quantity_in_offer"] = int(set_of_match.group(2))
            result["unit_weight_kg"] = float(weight_match.group(1).replace(',', '.'))
            result["pattern_matched"] = f"{set_of_match.group(0)} + {weight_match.group(0)}"
            return result
    
    # Pattern 5: Just weight, no quantity - do NOT assume qty=1!
    weight_only_match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', snippet_lower)
    if weight_only_match:
        result["unit_weight_kg"] = float(weight_only_match.group(1).replace(',', '.'))
        result["pattern_matched"] = weight_only_match.group(0)
    
    return result


def compute_unit_price(total_price: float, quantity_in_offer: int) -> Optional[float]:
    """
    v11: Compute unit price from total price and quantity.
    RULE: Only compute if quantity is explicitly known (not None, not 0).
    """
    if not total_price or total_price <= 0:
        return None
    if not quantity_in_offer or quantity_in_offer <= 0:
        return None
    return round(total_price / quantity_in_offer, 2)


def build_web_source_entry(
    price_item: Dict[str, Any],
    parsed_qty: Dict[str, Any],
    included_in_median: bool = True,
    excluded_reason: str = None
) -> Dict[str, Any]:
    """
    v11: Build complete web_sources entry with full audit trail.
    """
    total_price = price_item.get("price", 0)
    snippet = price_item.get("snippet", "")
    shop = price_item.get("shop", "unknown")
    
    qty = parsed_qty.get("quantity_in_offer")
    weight = parsed_qty.get("unit_weight_kg")
    pattern = parsed_qty.get("pattern_matched")
    
    unit_price = compute_unit_price(total_price, qty) if qty else None
    computed_total = round(unit_price * qty, 2) if unit_price and qty else None
    
    entry = {
        "shop": shop,
        "price": total_price,
        "snippet": snippet,
        "quantity_in_offer": qty,
        "unit_weight_kg": weight,
        "unit_price": unit_price,
        "computed_total_price": computed_total,
        "currency": "CHF",
        "pattern_matched": pattern,
        "included_in_median": included_in_median,
    }
    
    if excluded_reason:
        entry["excluded_reason"] = excluded_reason
    
    return entry


# ==============================================================================
# v7.3: BATCH WEB SEARCH WITH RATE LIMIT HANDLING
# ==============================================================================

def _call_claude_with_retry(
    prompt: str,
    max_tokens: int = 500,
    use_web_search: bool = False,
    max_retries: int = 2,
) -> Optional[str]:
    """
    v7.3.3: Call Claude with LONG wait on rate limit.
    """
    import time
    
    for attempt in range(max_retries):
        try:
            result = _call_claude(
                prompt=prompt,
                max_tokens=max_tokens,
                use_web_search=use_web_search,
            )
            return result
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower():
                wait_time = 120 if attempt == 0 else 180
                print(f"   ⏳ Rate limit hit, waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"   ⚠️ Claude error: {e}")
                return None
    
    print("   ⚠️ Rate limit still active after waiting")
    return None


def search_web_batch_for_new_prices(
    variant_keys: List[str],
    category: str = "unknown",
    query_analysis: Optional[Dict] = None
) -> Dict[str, Dict[str, Any]]:
    """
    v7.3.4: SINGLE WEB SEARCH STRATEGY - 83% cost reduction!
    
    Changes:
    - Wait 120s UPFRONT (proactive rate limit prevention)
    - ONE large batch (25 products) instead of multiple small batches
    - No retry logic needed (rate limit already handled)
    - Cost: $0.35 instead of $2.10 (6 batches × $0.35)
    
    v7.3.3: Uses clean_search_term() for better results
    """
    global RUN_COST_USD, WEB_SEARCH_COUNT_TODAY
    import time
    from query_analyzer import clean_search_term
    
    if not variant_keys:
        return {}
    
    # FIX #3: Check runtime mode and budget BEFORE websearch
    try:
        from runtime_mode import get_mode_config, is_budget_exceeded as mode_budget_check, should_use_websearch
        from config import load_config
        cfg = load_config()
        mode_config = get_mode_config(cfg.runtime.mode)
        
        # MODE_GUARD: Check if websearch allowed in this mode
        websearch_allowed = should_use_websearch(mode_config, WEB_SEARCH_COUNT_TODAY)
        print(f"\nMODE_GUARD:")
        print(f"  runtime_mode: {mode_config.mode.value}")
        print(f"  feature: websearch")
        print(f"  allowed: {str(websearch_allowed).lower()}")
        print(f"  reason: {'WEBSEARCH_LIMIT_REACHED' if not websearch_allowed else 'WITHIN_LIMITS'}")
        
        if not websearch_allowed:
            print(f"   🚫 Websearch limit reached ({WEB_SEARCH_COUNT_TODAY}/{mode_config.max_websearch_calls}) - using AI fallback")
            return {}
        
        # Check budget
        cost_summary = get_run_cost_summary()
        current_cost = cost_summary.get("total_usd", 0.0)
        budget_exceeded = mode_budget_check(mode_config, current_cost)
        
        # MODE_GUARD: Budget check
        print(f"\nMODE_GUARD:")
        print(f"  runtime_mode: {mode_config.mode.value}")
        print(f"  feature: websearch")
        print(f"  allowed: {str(not budget_exceeded).lower()}")
        print(f"  reason: {'BUDGET_EXCEEDED' if budget_exceeded else 'WITHIN_BUDGET'}")
        
        if budget_exceeded:
            print(f"   🚫 Budget exceeded (${current_cost:.2f}/${mode_config.max_run_cost_usd:.2f}) - stopping websearch")
            return {}
    except ImportError:
        # Fallback to old logic if runtime_mode not available
        # MODE_GUARD: Config-based websearch check
        print(f"\nMODE_GUARD:")
        print(f"  runtime_mode: unknown")
        print(f"  feature: websearch")
        print(f"  allowed: {str(WEB_SEARCH_ENABLED).lower()}")
        print(f"  reason: {'CONFIG_ENABLED' if WEB_SEARCH_ENABLED else 'CONFIG_DISABLED'}")
        
        if not WEB_SEARCH_ENABLED:
            print("   ℹ️ Web search DISABLED (config.yaml) - using AI estimation only")
            return {}
        
        if is_budget_exceeded():
            return {}
        
        if WEB_SEARCH_COUNT_TODAY >= DAILY_WEB_SEARCH_LIMIT:
            print("🚫 Daily web search limit reached")
            return {}
    
    # Claude with web search required
    if not _claude_client:
        print("   ⚠️ Web search requires Claude API")
        return {}
    
    results = {}
    
    # Check cache first for all variants
    uncached = []
    for vk in variant_keys:
        cached = get_cached_web_price(vk)
        if cached:
            results[vk] = cached
            get_cache_stats().record_web_price_hit()
            print(f"   💾 Cached: {vk[:40]}... = {cached['new_price']} CHF")
        else:
            uncached.append(vk)
            get_cache_stats().record_web_price_miss()
    
    if not uncached:
        return results
    
    # v7.3.4: SINGLE WEB SEARCH STRATEGY
    # Wait 120s UPFRONT to avoid rate limits completely
    # Then do ONE large batch with all products
    print(f"\n🌐 v7.3.4: SINGLE web search for {len(uncached)} products (cost-optimized)")
    print(f"   ⏳ Waiting 120s upfront (proactive rate limit prevention)...")
    time.sleep(120)
    
    # v12: DYNAMIC BATCH SIZING - Calculate optimal batch size based on token limits
    # Claude Sonnet max_tokens = 8000 (response) + input budget ~22k = 30k total safe limit
    # Estimated tokens per product in response: ~250 tokens (5 prices × 50 tokens each)
    # Safety margin: Use 200 tokens per product to avoid truncation
    MAX_RESPONSE_TOKENS = 8000
    ESTIMATED_TOKENS_PER_PRODUCT = 200
    max_products_per_batch = min(
        MAX_RESPONSE_TOKENS // ESTIMATED_TOKENS_PER_PRODUCT,
        40  # Hard cap
    )
    
    # 🧪 TEST MODE OVERRIDE: Hard limit to 1 product per batch
    try:
        from config import load_config
        from runtime_mode import get_mode_config
        cfg = load_config()
        mode_config = get_mode_config(cfg.runtime.mode)
        
        if mode_config.mode.value == "test":
            # 🧪 TEST MODE: Hard limit to 1 product total
            max_products_per_batch = 1
            print(f"   🧪 TEST MODE: Limiting websearch to 1 product (not {len(uncached)} products)")
            
            # CRITICAL: Truncate uncached list, not variant_keys
            max_total_products = mode_config.max_websearch_calls
            if len(uncached) > max_total_products:
                print(f"   🧪 TEST MODE: Truncating {len(uncached)} products to {max_total_products}")
                uncached = uncached[:max_total_products]
    except ImportError:
        pass  # Fallback to default behavior
    
    # Apply safety margin (80% of theoretical max)
    batch_size = int(max_products_per_batch * 0.8)  # ~32 products
    
    # 🧪 Ensure batch_size is at least 1 (TEST mode can set max_products_per_batch=1)
    if batch_size < 1:
        batch_size = 1
    
    print(f"   📊 Dynamic batch sizing: {batch_size} products/batch (max capacity: {max_products_per_batch})")
    
    for i in range(0, len(uncached), batch_size):
        batch = uncached[i:i + batch_size]
        
        print(f"\n   🌐 Web search batch {i//batch_size + 1}/{(len(uncached)-1)//batch_size + 1}: {len(batch)} products...")
        
        # v7.3.3: Clean search terms for better results
        # "Garmin Fenix 6 Smartwatch inkl. Zubehör" → "Garmin Fenix 6"
        cleaned_terms = []
        for idx, vk in enumerate(batch):
            # CRITICAL: Sanitize variant_key BEFORE cleaning
            # AI bundle detection can return names like "Hantelscheiben {'4x10kg': True}"
            # Step 1: Normalize to string
            vk_str = str(vk) if vk else ""
            if not vk_str.strip():
                continue
            
            # Step 2: Remove stringified dict/list artifacts using regex
            import re
            vk_str = re.sub(r'\{[^}]*\}', '', vk_str)  # Remove {...}
            vk_str = re.sub(r'\[[^\]]*\]', '', vk_str)  # Remove [...]
            
            # Step 3: Normalize whitespace
            vk_str = re.sub(r'\s+', ' ', vk_str).strip()
            
            # Step 4: Skip if empty after sanitization
            if not vk_str:
                print(f"   ⚠️ Skipping empty variant_key after sanitization")
                continue
            
            # Step 5: Apply clean_search_term for additional normalization
            clean = clean_search_term(vk_str, query_analysis)
            
            # FIX #3: DE-DUPLICATE TRAILING TOKENS - Remove duplicate words at end
            # Example: "Garmin fenix 6 Pro Pro" → "Garmin fenix 6 Pro"
            # Example: "Forerunner 255 Music Music" → "Forerunner 255 Music"
            tokens = clean.split()
            if len(tokens) >= 2 and tokens[-1].lower() == tokens[-2].lower():
                tokens = tokens[:-1]
                clean = " ".join(tokens)
                print(f"   🔧 Deduplicated: removed duplicate '{tokens[-1]}'")
            
            # WEBSEARCH QUERY GUARD: Skip too short or generic queries
            # These waste money and produce poor results → fallback to AI estimate
            # Examples: "Pro", "Set", "Band", single words < 4 chars
            if len(clean) < 4 or (len(tokens) == 1 and len(clean) < 8):
                print(f"   ⚠️ Skipping websearch for too short/generic query: '{clean}' → will use AI estimate")
                continue
            
            # Skip common generic terms that won't produce good web results
            generic_terms = {'pro', 'set', 'band', 'kit', 'pack', 'bundle', 'lot'}
            if len(tokens) == 1 and clean.lower() in generic_terms:
                print(f"   ⚠️ Skipping websearch for generic term: '{clean}' → will use AI estimate")
                continue
            
            cleaned_terms.append((idx, vk_str, clean))
            if clean != vk_str:
                print(f"   🔧 Cleaned: '{vk_str[:40]}' → '{clean}'")
        
        # OBSERVABILITY: Log websearch input for debugging
        for idx, vk_original, clean_query in cleaned_terms:
            print(f"   🔎 Websearch input: product='{clean_query}' | query=\"{clean_query}\"")
        
        product_list = "\n".join([f"{idx+1}. {clean}" for idx, vk, clean in cleaned_terms])
        
        # v12: AI-based shop suggestions per product category
        # First, ask AI which shops are relevant for this product category
        shop_prompt = f"""Welche Schweizer Online-Shops sind am besten für diese Produktkategorie?

Kategorie: {category}
Beispiel-Produkte: {', '.join([clean for _, _, clean in cleaned_terms[:3]])}

Liste 5-8 relevante Schweizer Shops die diese Produkte verkaufen.
Antworte NUR als komma-separierte Liste:
Shop1.ch, Shop2.ch, Shop3.ch, ...

Beispiele:
- Elektronik: Digitec.ch, Galaxus.ch, MediaMarkt.ch, Interdiscount.ch, Manor.ch
- Fitness: Decathlon.ch, Brack.ch, Gonser.ch, BodySport.ch, Gorilla-Sports.ch
- Kleidung: Zalando.ch, Manor.ch, Ochsner-Sport.ch, SportXX.ch
- Haustier: Fressnapf.ch, Qualipet.ch, Brack.ch, Zooplus.ch"""
        
        try:
            shop_response = _call_claude_with_retry(
                prompt=shop_prompt,
                max_tokens=150,
                use_web_search=False,
                max_retries=1,
            )
            
            if shop_response:
                # Extract shop list from response
                shops_line = shop_response.strip().split('\n')[0]
                relevant_shops = shops_line.strip()
            else:
                # Fallback to general shops
                relevant_shops = "Digitec.ch, Galaxus.ch, Brack.ch, Manor.ch, Interdiscount.ch"
        except:
            # Fallback to general shops
            relevant_shops = "Digitec.ch, Galaxus.ch, Brack.ch, Manor.ch, Interdiscount.ch"
        
        print(f"   🏪 Relevant shops for {category}: {relevant_shops}")
        print(f"   🔎 Searching for {len(cleaned_terms)} products...")
        
        # v11: Enhanced prompt - request snippets for qty parsing audit trail
        prompt = f"""Finde Schweizer Neupreise (CHF) für diese {len(batch)} Produkte.
Kategorie: {category}

PRODUKTE:
{product_list}

Suche in: {relevant_shops}

WICHTIG: 
1. Finde MEHRERE Preise pro Produkt (bis zu 5 Shops)
2. Inkludiere "snippet" mit Produktbeschreibung (für Mengenangaben wie "2×5kg", "Paar", "Set of 2")

Antworte NUR als JSON-Array:
[
  {{"nr": 1, "prices": [{{"price": 49.90, "shop": "Galaxus", "snippet": "ATX Bumper 2×5kg Set"}}, {{"price": 52.00, "shop": "Digitec", "snippet": "ATX Bumper 5kg single"}}], "conf": 0.9}},
  {{"nr": 2, "prices": [], "conf": 0.0}},
  ...
]

Bei unbekannt: prices=[], conf=0"""

        try:
            raw = _call_claude_with_retry(
                prompt=prompt,
                max_tokens=800,
                use_web_search=True,
                max_retries=3,
            )
            
            if not raw:
                print("   ⚠️ No response from batch web search")
                continue
            
            # Track cost (one web search for the batch)
            add_cost(COST_CLAUDE_WEB_SEARCH)
            WEB_SEARCH_COUNT_TODAY += 1
            
            # Parse JSON array response
            json_match = re.search(r'\[[\s\S]*\]', raw)
            if not json_match:
                print(f"   No JSON array in batch response")
                
                # TEST MODE: Do NOT use expensive AI fallback
                try:
                    from config import load_config
                    from runtime_mode import get_mode_config
                    cfg = load_config()
                    mode_config = get_mode_config(cfg.runtime.mode)
                    
                    if mode_config.mode.value == "test":
                        print(f"   TEST MODE: Skipping AI fallback (would cost ${len(batch) * 0.003:.3f})")
                        continue
                except ImportError:
                    pass
                
                print(f"   JSON parse failed - using AI fallback for {len(batch)} products")
                continue
            
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError as e:
                print(f"   Batch web search failed: {e}")
                print(f"   Raw JSON (first 500 chars): {json_match.group(0)[:500]}")
                
                # TEST MODE: Do NOT use expensive AI fallback
                try:
                    from config import load_config
                    from runtime_mode import get_mode_config
                    cfg = load_config()
                    mode_config = get_mode_config(cfg.runtime.mode)
                    
                    if mode_config.mode.value == "test":
                        print(f"   TEST MODE: Skipping AI fallback (would cost ${len(batch) * 0.003:.3f})")
                        continue
                except ImportError:
                    pass
                
                print(f"   JSON parse failed - using AI fallback for {len(batch)} products")
                continue
            
            for item in parsed:
                nr = item.get("nr", 0) - 1  # Convert to 0-indexed
                if 0 <= nr < len(batch):
                    vk = batch[nr]
                    prices_list = item.get("prices", [])
                    conf = item.get("conf", 0.0)
                    
                    # v11: EXPLICIT QUANTITY PARSING + FULL AUDIT TRAIL
                    # Parse qty from snippets, compute unit prices, build web_sources
                    if prices_list and conf >= 0.6:
                        # Build web_sources entries with full audit trail
                        web_sources = []
                        valid_prices = []
                        unit_prices = []  # For qty-adjusted median
                        shops = []
                        has_qty_data = False
                        
                        for price_item in prices_list[:5]:
                            p = price_item.get("price")
                            s = price_item.get("shop")
                            snippet = price_item.get("snippet", "")
                            
                            if not p or p <= 0:
                                continue
                            
                            # Parse quantity from snippet
                            parsed_qty = parse_quantity_from_snippet(snippet)
                            
                            # Build audit entry
                            entry = build_web_source_entry(
                                price_item, parsed_qty, 
                                included_in_median=True
                            )
                            web_sources.append(entry)
                            
                            # Collect prices
                            valid_prices.append(float(p))
                            shops.append(s or "unknown")
                            
                            # If qty explicit, use unit price for median
                            if parsed_qty.get("quantity_in_offer"):
                                has_qty_data = True
                                unit_p = entry.get("unit_price")
                                if unit_p:
                                    unit_prices.append(unit_p)
                                    print(f"      📊 {s}: {p:.2f} CHF / {parsed_qty['quantity_in_offer']} = {unit_p:.2f} CHF/Stück")
                        
                        if valid_prices:
                            # Decide which prices to use for median
                            # If we have unit prices from qty parsing, use those
                            if unit_prices and len(unit_prices) >= 1:
                                prices_for_median = unit_prices
                                use_unit_prices = True
                            else:
                                prices_for_median = valid_prices
                                use_unit_prices = False
                            
                            # Compute initial median
                            prices_sorted = sorted(prices_for_median)
                            n = len(prices_sorted)
                            if n == 1:
                                median_price = prices_sorted[0]
                                final_prices = prices_sorted
                            else:
                                if n % 2 == 0:
                                    median_price = (prices_sorted[n//2 - 1] + prices_sorted[n//2]) / 2
                                else:
                                    median_price = prices_sorted[n//2]
                                
                                # Remove outliers: ±40% of median
                                lower_bound = median_price * 0.6
                                upper_bound = median_price * 1.4
                                final_prices = []
                                
                                for i, p in enumerate(prices_for_median):
                                    if lower_bound <= p <= upper_bound:
                                        final_prices.append(p)
                                        if i < len(web_sources):
                                            web_sources[i]["included_in_median"] = True
                                    else:
                                        if i < len(web_sources):
                                            web_sources[i]["included_in_median"] = False
                                            if p < lower_bound:
                                                web_sources[i]["excluded_reason"] = "outlier_below_40pct"
                                            else:
                                                web_sources[i]["excluded_reason"] = "outlier_above_40pct"
                                
                                # Recompute median after outlier removal
                                if final_prices:
                                    final_sorted = sorted(final_prices)
                                    n_final = len(final_sorted)
                                    if n_final % 2 == 0:
                                        median_price = (final_sorted[n_final//2 - 1] + final_sorted[n_final//2]) / 2
                                    else:
                                        median_price = final_sorted[n_final//2]
                                else:
                                    final_prices = prices_sorted
                            
                            # Determine price_source
                            if use_unit_prices:
                                price_source = PRICE_SOURCE_WEB_QTY_ADJUSTED if len(final_prices) >= 2 else PRICE_SOURCE_WEB_SINGLE
                            elif len(final_prices) >= 2:
                                price_source = PRICE_SOURCE_WEB_MEDIAN
                            else:
                                price_source = PRICE_SOURCE_WEB_SINGLE
                            
                            result = {
                                "new_price": round(median_price, 2),
                                "price_source": price_source,
                                "shop_name": ", ".join(shops[:3]),
                                "confidence": conf,
                                "market_sample_size": len(final_prices),
                                "market_value": round(median_price, 2),
                                "market_based": True,
                                "web_sources": web_sources,  # v11: Full audit trail
                            }
                            
                            # Cache it
                            set_cached_web_price(vk, result["new_price"], price_source, result["shop_name"])
                            results[vk] = result
                            
                            # Enhanced logging
                            if use_unit_prices:
                                print(f"   ✅ {vk[:40]}... = {median_price:.2f} CHF/Stück (qty-adjusted median of {len(final_prices)})")
                            elif len(final_prices) >= 2:
                                print(f"   ✅ {vk[:40]}... = {median_price:.2f} CHF (median of {len(final_prices)} prices)")
                            else:
                                print(f"   ✅ {vk[:40]}... = {median_price:.2f} CHF ({shops[0]})")
                        else:
                            print(f"   ⚠️ {vk[:40]}... = no valid prices")
                    else:
                        print(f"   ⚠️ {vk[:40]}... = no price found")
                        
        except Exception as e:
            print(f"   ⚠️ Batch web search failed: {e}")
    
    return results


# ==============================================================================
# v6.8: WEIGHT-BASED PRICING VALIDATION (unchanged)
# ==============================================================================

WEIGHT_PRICING = {
    "standard": {"new_price_per_kg": 3.5, "resale_rate": 0.60},  # Gusseisen
    "bumper": {"new_price_per_kg": 5.0, "resale_rate": 0.55},    # Bumper Plates
    "competition": {"new_price_per_kg": 9.0, "resale_rate": 0.50}, # Competition/Calibrated (v9.0: erhöht von 8)
    "rubber": {"new_price_per_kg": 4.0, "resale_rate": 0.55},    # Rubber coated
    "calibrated": {"new_price_per_kg": 9.0, "resale_rate": 0.50}, # v9.0: Calibrated = Competition
}

WEIGHT_PLATE_KEYWORDS = [
    # Deutsch
    "hantelscheiben", "hantelscheibe", "gewichte", "gewicht",
    "hantel", "langhantel", "kurzhantel", "kettlebell", "bumper",
    "hantelset", "gewichtsscheibe", "gewichtsscheiben",
    # Englisch
    "plates", "plate", "weight plate", "dumbbell", "barbell",
    # Französisch (v9.0)
    "disques", "disque", "musculation", "haltère", "poids",
    # Technische
    "olympia", "50mm", "30mm",
]


def is_weight_plate(text: str) -> bool:
    """Check if text describes weight plates/fitness equipment."""
    text_lower = text.lower()
    for kw in WEIGHT_PLATE_KEYWORDS:
        if kw in text_lower:
            return True
    return False


def extract_weight_kg(text: str) -> Optional[float]:
    """
    v7.3.3: Improved weight extraction from text.
    Handles patterns like:
    - "20kg", "20 kg" → 20
    - "4x 5kg" → 20 (total)
    - "Set 4x 5kg" → 20 (total)
    - "8x1.25kg" → 10 (total)
    """
    import re
    text_lower = text.lower()
    
    # Pattern 1: Quantity x Weight (e.g., "4x 5kg", "8x1.25kg")
    qty_match = re.search(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', text_lower)
    if qty_match:
        qty = int(qty_match.group(1))
        per_piece = float(qty_match.group(2).replace(',', '.'))
        return qty * per_piece
    
    # Pattern 2: Total weight (e.g., "20kg", "12.5 kg")
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', text_lower)
    if match:
        return float(match.group(1).replace(',', '.'))
    return None


def get_weight_type(text: str) -> str:
    """Determine weight plate type from text."""
    text_lower = text.lower()
    
    # v9.0: Explicit keyword detection for weight types
    # Calibrated/Competition plates (most expensive)
    if any(kw in text_lower for kw in ["calibr", "kalib", "competition", "wettkampf", "ipf", "iwf"]):
        return "calibrated"
    
    # Bumper plates
    if any(kw in text_lower for kw in ["bumper", "urethane", "pu-", "stoßdämpf"]):
        return "bumper"
    
    # Rubber coated
    if any(kw in text_lower for kw in ["rubber", "gummi", "beschicht"]):
        return "rubber"
    
    # Default: standard cast iron
    return "standard"


def validate_weight_price(text: str, price: float, is_resale: bool = True) -> Tuple[float, str]:
    """
    Validate weight plate pricing - ONLY for single-source fallbacks.
    
    MEDIAN-FIRST RULE: This is NOT applied to web_median prices.
    Only used for: web_single, ai_estimate, query_baseline
    """
    if not is_weight_plate(text):
        return price, "not_weight_plate"

    weight_kg = extract_weight_kg(text)
    if not weight_kg or weight_kg <= 0:
        return price, "no_weight_found"

    weight_type = get_weight_type(text)
    pricing = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])

    if is_resale:
        max_price = weight_kg * pricing["max_resale_per_kg"]
        typical_price = weight_kg * pricing["typical_resale_per_kg"]
    else:
        max_price = weight_kg * pricing["new_price_per_kg"]
        typical_price = max_price * 0.8

    if price > max_price:
        return typical_price, f"capped_to_{weight_type}_{weight_kg}kg"

    return price, f"valid_{weight_type}_{weight_kg}kg"


# ==============================================================================
# CACHE MANAGEMENT
# ==============================================================================

_variant_cache: Dict[str, Dict] = {}
_component_cache: Dict[str, Dict] = {}
_cluster_cache: Dict[str, Dict] = {}

def _load_caches():
    """Load all caches from disk."""
    global _variant_cache, _component_cache, _cluster_cache, _web_price_cache
    
    try:
        if os.path.exists(VARIANT_CACHE_FILE):
            with open(VARIANT_CACHE_FILE, "r", encoding="utf-8") as f:
                _variant_cache = json.load(f)
    except:
        _variant_cache = {}
    
    try:
        if os.path.exists(COMPONENT_CACHE_FILE):
            with open(COMPONENT_CACHE_FILE, "r", encoding="utf-8") as f:
                _component_cache = json.load(f)
    except:
        _component_cache = {}
    
    try:
        if os.path.exists(CLUSTER_CACHE_FILE):
            with open(CLUSTER_CACHE_FILE, "r", encoding="utf-8") as f:
                _cluster_cache = json.load(f)
    except:
        _cluster_cache = {}
    
    try:
        if os.path.exists(WEB_PRICE_CACHE_FILE):
            with open(WEB_PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                _web_price_cache = json.load(f)
    except:
        _web_price_cache = {}

def _save_cluster_cache():
    """Save cluster cache to disk."""
    if not CACHE_ENABLED:
        return
    try:
        with open(CLUSTER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cluster_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"{e}")

def get_cache_duration_for_category(variant_key: str) -> int:
    """
    Get cache duration based on product category.
    RULE: Never shorten below WEB_PRICE_CACHE_DAYS (60). Only extend for stable categories.
    
    Args:
        variant_key: Product variant identifier
    
    Returns:
        int: Cache duration in days
    """
    vk_lower = variant_key.lower()
    
    # Fitness equipment: prices stable for months (extend to 120 days)
    fitness_keywords = ["hantel", "gewicht", "plate", "bank", "rack", "fitness", "bumper", "scheibe"]
    if any(kw in vk_lower for kw in fitness_keywords):
        return 120  # 4 months (extended from 60)
    
    # All other categories: use default (60 days)
    # Electronics, clothing, luxury goods remain at 60 days
    return WEB_PRICE_CACHE_DAYS  # 60 days (never shortened)

def is_commodity_variant(variant_key: str, category: str, websearch_query: Optional[str] = None) -> bool:
    """
    Check if variant is a commodity with stable prices.
    
    CONSERVATIVE DETECTION (CORRECTED):
    - Uses websearch_query (display_name) as primary signal, NOT variant_key
    - Only skips websearch when confident (explicit signals)
    - Ambiguous cases → do websearch (safe default)
    
    Commodities:
    1. Fitness weights with explicit weight in websearch_query
    2. Standard accessories (cables, adapters, bands)
    
    Args:
        variant_key: Product variant identifier (normalized, often generic)
        category: Category string (used cautiously)
        websearch_query: The actual search query string (display_name/final_search_name)
    
    Returns:
        bool: True if commodity (skip websearch), False otherwise
    """
    # Use websearch_query as primary signal (more specific than variant_key)
    search_text = (websearch_query or variant_key).lower()
    
    # SIGNAL 1: Explicit weight + fitness keywords = commodity
    # Example: "Hantelscheibe 5kg Gusseisen" or "Bumper Plate 20kg"
    has_explicit_weight = bool(re.search(r'\d+(?:[.,]\d+)?\s*kg', search_text))
    fitness_keywords = ["hantel", "gewicht", "plate", "scheibe", "bumper", "disc"]
    
    if has_explicit_weight and any(kw in search_text for kw in fitness_keywords):
        return True  # Commodity: stable CHF/kg pricing
    
    # SIGNAL 2: Accessory allowlist (stable prices, <50 CHF)
    accessory_keywords = [
        "kabel", "cable", "ladegerät", "charger", "adapter",
        "armband", "band", "strap",  # Watch bands
        "clip", "halter", "holder",
    ]
    if any(kw in search_text for kw in accessory_keywords):
        return True  # Commodity: accessories have stable prices
    
    # Default: NOT commodity (do websearch)
    # This includes:
    # - Generic patterns without explicit weight ("Weight Plates", "weight_plates")
    # - Electronics (prices vary)
    # - Clothing (sizes/styles vary)
    # - Any ambiguous case
    return False

def get_cached_web_price(variant_key: str) -> Optional[Dict[str, Any]]:
    """Get cached web price for a variant."""
    global _web_price_cache
    
    if variant_key in _web_price_cache:
        cached = _web_price_cache[variant_key]
        cached_at = cached.get("cached_at", "")
        
        if cached_at:
            try:
                cached_date = datetime.datetime.fromisoformat(cached_at)
                age_days = (datetime.datetime.now() - cached_date).days
                
                # OPTIMIZATION: Category-specific cache duration
                cache_days = get_cache_duration_for_category(variant_key)
                
                if age_days < cache_days:
                    return {
                        "new_price": cached.get("new_price"),
                        "price_source": cached.get("price_source"),
                        "shop_name": cached.get("shop_name"),
                        "confidence": cached.get("confidence", 0.8),
                    }
            except:
                pass
    
    return None

def set_cached_web_price(variant_key: str, new_price: float, price_source: str, shop_name: str):
    """Cache a web price for a variant."""
    global _web_price_cache
    
    _web_price_cache[variant_key] = {
        "new_price": new_price,
        "price_source": price_source,
        "shop_name": shop_name,
        "confidence": 0.8,
        "cached_at": datetime.datetime.now().isoformat(),
    }
    
    if CACHE_ENABLED:
        try:
            with open(WEB_PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_web_price_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Web price cache save failed: {e}")

def get_cached_variant_info(variant_key: str) -> Optional[Dict[str, Any]]:
    """Get cached variant info."""
    global _variant_cache
    
    if variant_key in _variant_cache:
        cached = _variant_cache[variant_key]
        cached_at = cached.get("cached_at", "")
        
        if cached_at:
            try:
                cached_date = datetime.datetime.fromisoformat(cached_at)
                age_days = (datetime.datetime.now() - cached_date).days
                
                if age_days < VARIANT_CACHE_DAYS:
                    return cached
            except:
                pass
    
    return None

def set_cached_variant_info(variant_key: str, new_price: float, transport_car: bool, resale_price: float, is_bundle: bool, bundle_component_count: int):
    """Cache variant info."""
    global _variant_cache
    
    _variant_cache[variant_key] = {
        "new_price": new_price,
        "transport_car": transport_car,
        "resale_price": resale_price,
        "is_bundle": is_bundle,
        "bundle_component_count": bundle_component_count,
        "cached_at": datetime.datetime.now().isoformat(),
    }
    
    if CACHE_ENABLED:
        try:
            with open(VARIANT_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_variant_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Variant cache save failed: {e}")

def _get_new_price_estimate(query_analysis: Optional[Dict]) -> float:
    """Extract new price estimate from query analysis."""
    if not query_analysis:
        return 100.0
    
    new_price = query_analysis.get("new_price_estimate")
    if new_price and new_price > 0:
        return float(new_price)
    
    return 100.0

def _get_min_realistic_price(query_analysis: Optional[Dict]) -> float:
    """Extract minimum realistic price from query analysis."""
    if not query_analysis:
        return 10.0
    
    min_price = query_analysis.get("min_realistic_price")
    if min_price and min_price > 0:
        return float(min_price)
    
    return 10.0

def _get_category(query_analysis: Optional[Dict]) -> str:
    """Extract category from query analysis."""
    if not query_analysis:
        return "unknown"
    
    category = query_analysis.get("category")
    if category:
        return str(category)
    
    return "unknown"

def _get_resale_rate(query_analysis: Optional[Dict]) -> float:
    """Extract resale rate from query analysis."""
    if not query_analysis:
        return 0.50
    
    resale_rate = query_analysis.get("resale_rate")
    if resale_rate and resale_rate > 0:
        return float(resale_rate)
    
    return 0.50

def _get_auction_multiplier(query_analysis: Optional[Dict]) -> float:
    """Get typical auction price multiplier for category."""
    if not query_analysis:
        return 2.0
    
    category = query_analysis.get("category", "unknown")
    
    # Category-specific multipliers
    multipliers = {
        "electronics": 1.5,
        "clothing": 2.5,
        "fitness": 1.8,
        "toys": 2.0,
        "collectibles": 3.0,
        "tools": 1.5,
        "furniture": 1.3,
    }
    
    return multipliers.get(category, 2.0)

def predict_final_auction_price(
    current_price: float,
    bids_count: int,
    hours_remaining: float,
    median_price: Optional[float] = None,
    new_price: Optional[float] = None,
    typical_multiplier: float = 2.0,
) -> Dict[str, Any]:
    """Predict final auction price based on current state."""
    if not current_price or current_price <= 0:
        return {"predicted_final_price": 0, "confidence": 0, "method": "no_price"}
    
    # If auction is ending soon with many bids, price is likely final
    if hours_remaining < 2 and bids_count >= 5:
        return {
            "predicted_final_price": current_price * 1.05,
            "confidence": 0.85,
            "method": "ending_soon_high_activity"
        }
    
    if hours_remaining < 6 and bids_count >= 3:
        return {
            "predicted_final_price": current_price * 1.10,
            "confidence": 0.75,
            "method": "ending_soon"
        }
    
    # Use median price if available
    if median_price and median_price > current_price:
        predicted = min(median_price, current_price * typical_multiplier)
        return {
            "predicted_final_price": predicted,
            "confidence": 0.60,
            "method": "median_based"
        }
    
    # Fallback: estimate based on bid activity
    if bids_count >= 10:
        multiplier = 1.3
    elif bids_count >= 5:
        multiplier = 1.5
    elif bids_count >= 2:
        multiplier = 1.8
    else:
        multiplier = typical_multiplier
    
    predicted = current_price * multiplier
    
    # Cap at new price if known
    if new_price and predicted > new_price * 0.90:
        predicted = new_price * 0.90
    
    # v9.0 FIX: predicted_final can NEVER be less than current_price!
    # This is logically impossible - auctions only go UP
    if predicted < current_price:
        predicted = current_price * 1.1  # At least 10% above current
    
    return {
        "predicted_final_price": round(predicted, 2),
        "confidence": 0.50,
        "method": "bid_activity_estimate"
    }

# ==============================================================================
# CATEGORY THRESHOLD CACHE (v7.2.2)
# ==============================================================================

_category_threshold_cache: Dict[str, Dict] = {}

def _load_category_threshold_cache():
    """v7.2.2: Loads category threshold cache from disk."""
    global _category_threshold_cache
    
    try:
        if os.path.exists(CATEGORY_THRESHOLD_CACHE_FILE):
            with open(CATEGORY_THRESHOLD_CACHE_FILE, "r", encoding="utf-8") as f:
                _category_threshold_cache = json.load(f)
            
            now = datetime.datetime.now().isoformat()
            expired = [k for k, v in _category_threshold_cache.items() 
                      if v.get("expires_at", "") < now]
            for k in expired:
                del _category_threshold_cache[k]
            
            if expired:
                _save_category_threshold_cache()
                
    except Exception as e:
        print(f"⚠️ Category threshold cache load failed: {e}")
        _category_threshold_cache = {}


def _save_category_threshold_cache():
    """v7.2.2: Saves category threshold cache to disk."""
    if not CACHE_ENABLED:
        return
    try:
        with open(CATEGORY_THRESHOLD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_category_threshold_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Category threshold cache save failed: {e}")


def get_category_threshold(category: str) -> Dict[str, float]:
    """v7.2.2: Get or calculate category-specific validation thresholds.
    
    Returns:
        {
            "min_single_bid_ratio": 0.40,  # Minimum % of new price for single bid
            "min_buy_now_ratio": 0.30,     # Minimum % of buy-now for single bid
            "depreciation_rate": 0.50,     # How fast value drops (electronics=0.50, fitness=0.30)
        }
    """
    global _category_threshold_cache
    
    _load_category_threshold_cache()
    
    # Check cache
    if category in _category_threshold_cache:
        cached = _category_threshold_cache[category]
        if cached.get("expires_at", "") > datetime.datetime.now().isoformat():
            return {
                "min_single_bid_ratio": cached.get("min_single_bid_ratio", 0.40),
                "min_buy_now_ratio": cached.get("min_buy_now_ratio", 0.30),
                "depreciation_rate": cached.get("depreciation_rate", 0.50),
            }
    
    # Ask AI to calculate thresholds
    print(f"   🤖 Calculating category thresholds for: {category}")
    
    prompt = f"""Analysiere die Kategorie "{category}" für ricardo.ch Wiederverkauf.

Bestimme:
1. Wie schnell verliert diese Kategorie an Wert? (depreciation_rate: 0.0-1.0)
   - 0.70-0.80 = sehr schnell (z.B. Smartphones, Mode)
   - 0.40-0.60 = mittel (z.B. Laptops, Uhren)
   - 0.20-0.30 = langsam (z.B. Fitness-Gewichte, Werkzeug)

2. Minimum akzeptabler Gebotspreis bei 1 Gebot (min_single_bid_ratio: 0.0-1.0)
   - Prozent vom Neupreis
   - Schneller Wertverlust = höherer Threshold (0.50)
   - Langsamer Wertverlust = niedrigerer Threshold (0.30)

3. Minimum akzeptabler Gebotspreis vs Buy-Now (min_buy_now_ratio: 0.0-1.0)
   - Prozent vom Buy-Now Preis
   - Meist 0.30 (30%)

BEISPIELE:
- electronics: depreciation=0.50, min_single_bid=0.40, min_buy_now=0.30
- fitness: depreciation=0.30, min_single_bid=0.30, min_buy_now=0.30
- clothing: depreciation=0.70, min_single_bid=0.50, min_buy_now=0.40
- tools: depreciation=0.25, min_single_bid=0.30, min_buy_now=0.30

Antworte NUR als JSON:
{{
  "depreciation_rate": 0.50,
  "min_single_bid_ratio": 0.40,
  "min_buy_now_ratio": 0.30,
  "reasoning": "Kurze Erklärung"
}}"""
    
    try:
        raw = call_ai(prompt, max_tokens=300)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                depreciation_rate = float(parsed.get("depreciation_rate", 0.50))
                min_single_bid_ratio = float(parsed.get("min_single_bid_ratio", 0.40))
                min_buy_now_ratio = float(parsed.get("min_buy_now_ratio", 0.30))
                reasoning = parsed.get("reasoning", "")
                
                # Cache for 90 days
                now = datetime.datetime.now()
                expires = now + datetime.timedelta(days=90)
                
                _category_threshold_cache[category] = {
                    "depreciation_rate": depreciation_rate,
                    "min_single_bid_ratio": min_single_bid_ratio,
                    "min_buy_now_ratio": min_buy_now_ratio,
                    "reasoning": reasoning,
                    "cached_at": now.isoformat(),
                    "expires_at": expires.isoformat(),
                }
                
                _save_category_threshold_cache()
                
                print(f"   ✅ Category thresholds: depreciation={depreciation_rate:.0%}, single_bid={min_single_bid_ratio:.0%}, buy_now={min_buy_now_ratio:.0%}")
                print(f"      Reasoning: {reasoning}")
                
                return {
                    "min_single_bid_ratio": min_single_bid_ratio,
                    "min_buy_now_ratio": min_buy_now_ratio,
                    "depreciation_rate": depreciation_rate,
                }
    except Exception as e:
        print(f"⚠️ Category threshold calculation failed: {e}")
    
    # Fallback to defaults
    return {
        "min_single_bid_ratio": 0.40,
        "min_buy_now_ratio": 0.30,
        "depreciation_rate": 0.50,
    }


def calculate_confidence_weight(bids: int, hours: float) -> float:
    """Calculate confidence weight based on bid count and time remaining.
    
    CRITICAL: 1-bid listings are WEAK SIGNALS and must never dominate.
    """
    # Bid-based weight (strict hierarchy)
    if bids >= 5:
        bid_weight = 1.00  # Strong signal
    elif bids >= 3:
        bid_weight = 0.80  # Good signal
    elif bids == 2:
        bid_weight = 0.60  # Moderate signal
    elif bids == 1:
        bid_weight = 0.35  # WEAK signal (never dominant)
    else:
        bid_weight = 0.10  # No bids (should be filtered out)
    
    # Time-based adjustment (minor)
    time_weight = 1.0 if hours < 6 else (0.9 if hours < 24 else 0.8)
    
    return bid_weight * time_weight


def weighted_median(price_samples: List[Dict[str, Any]]) -> float:
    """Calculate weighted median from price samples."""
    if not price_samples:
        return 0.0
    
    if len(price_samples) == 1:
        return price_samples[0]["price"]
    
    # Sort by price
    sorted_samples = sorted(price_samples, key=lambda x: x["price"])
    
    # Calculate total weight
    total_weight = sum(s["weight"] for s in sorted_samples)
    
    if total_weight == 0:
        # Fallback to simple median
        return sorted_samples[len(sorted_samples) // 2]["price"]
    
    # Find weighted median
    cumulative_weight = 0.0
    target_weight = total_weight / 2.0
    
    for sample in sorted_samples:
        cumulative_weight += sample["weight"]
        if cumulative_weight >= target_weight:
            return sample["price"]
    
    # Fallback
    return sorted_samples[-1]["price"]


def is_realistic_auction_price(current_price: float, bids_count: int, hours_remaining: float, reference_price: float, for_market_calculation: bool = True) -> Tuple[bool, str]:
    """v7.2.1: Improved validation - reject early auctions with unrealistic prices."""
    if not current_price or current_price <= 0:
        return False, "no_price"
    if not reference_price or reference_price <= 0:
        reference_price = 100.0
    price_ratio = current_price / reference_price if reference_price > 0 else 0

    # v7.2.1: Early auction check - even with many bids, price must be realistic
    # Example: iPhone (1500 CHF) at 22 CHF after 1 day with 20 bids → REJECT
    if price_ratio < 0.20:
        return False, f"unrealistic_price_{price_ratio*100:.0f}pct"
    
    if bids_count >= VERY_HIGH_ACTIVITY_BID_THRESHOLD:
        # v7.2.1: Even with 20+ bids, require minimum 15% of reference price
        if price_ratio >= 0.15:
            return True, "very_high_activity_trusted"
        else:
            return False, f"very_high_activity_too_low_{price_ratio*100:.0f}pct"
    
    if bids_count >= HIGH_ACTIVITY_BID_THRESHOLD:
        if price_ratio >= HIGH_ACTIVITY_MIN_PRICE_RATIO:
            return True, "high_activity_validated"
        else:
            return False, f"high_activity_low_price_{price_ratio*100:.0f}pct"

    if for_market_calculation:
        # REVISED: Bidding intensity matters more than time
        # Accept early auctions if they have strong bidding activity
        minimum_for_market = max(reference_price * 0.20, 10.0)
        
        # High activity overrides time concerns
        if bids_count >= 5:
            if current_price >= minimum_for_market:
                return True, "market_high_activity"
        
        # Ending soon with reasonable activity
        if hours_remaining < 12:
            if current_price >= minimum_for_market:
                return True, "market_ending_soon_good_price"
            if bids_count >= 3 and price_ratio >= 0.12:
                return True, "market_moderate_activity"
        
        # Very late auctions with any activity
        if hours_remaining < 2 and bids_count >= 2:
            return True, "market_ending_now"
        
        return False, "market_insufficient_data"

    minimum_threshold = max(reference_price * UNREALISTIC_PRICE_RATIO, 10.0)
    if current_price >= minimum_threshold:
        return True, "above_threshold"
    if hours_remaining < 2:
        return True, "ending_now"
    if hours_remaining < MIN_HOURS_FOR_PRICE_TRUST and bids_count >= MODERATE_BID_COUNT:
        return True, "ending_soon_active"
    if bids_count >= HIGH_DEMAND_BID_COUNT:
        return True, "high_demand_validated"
    return False, f"below_{minimum_threshold:.0f}_insufficient_validation"


def apply_global_sanity_check(resale_price: float, reference_price: float, is_bundle: bool, source: str) -> float:
    """Apply global sanity checks to prevent unrealistic resale prices."""
    if not reference_price or reference_price <= 0:
        return resale_price
    
    max_allowed = reference_price * (MAX_BUNDLE_RESALE_PERCENT_OF_NEW if is_bundle else MAX_RESALE_PERCENT_OF_NEW)
    
    if resale_price > max_allowed:
        return max_allowed
    
    return resale_price


def calculate_market_resale_from_listings(
    variant_key: str,
    listings: List[Dict[str, Any]],
    reference_price: float,
    unrealistic_floor: float = 10.0,
    context=None,
    ua: str = None,
    variant_new_price: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Calculate market resale price from auction listings."""
    if not variant_key:
        return None
    
    has_variant_specific_price = (
        variant_new_price is not None and 
        variant_new_price > 0 and 
        abs(variant_new_price - reference_price) > 10
    )
    sanity_reference = variant_new_price if has_variant_specific_price else None
    
    price_samples = []
    buy_now_ceiling = None
    
    for listing in listings:
        if listing.get("variant_key") != variant_key:
            continue
        
        current = listing.get("current_price_ricardo")
        bids = listing.get("bids_count") or 0
        hours = listing.get("hours_remaining") or 999
        buy_now = listing.get("buy_now_price")
        
        # v7.2.2: Track buy-now prices (but only from listings WITH bids)
        if buy_now and buy_now > unrealistic_floor and bids > 0:
            if buy_now_ceiling is None or buy_now < buy_now_ceiling:
                buy_now_ceiling = buy_now
        
        # v7.2.2: IGNORE pure buy-now listings (no bids)
        if not current or current <= 0 or bids == 0:
            continue
        
        # FINE-TUNED: 1-bid listings are WEAK SIGNALS only
        if bids == 1:
            price_ratio = current / reference_price if reference_price > 0 else 0
            
            # HARD EXCLUSION: price_ratio < 0.45 (raised from 0.20/0.40)
            if price_ratio < 0.45:
                continue  # Too low for 1-bid listing
            
            # HARD EXCLUSION: Clear start-price effect
            if current <= 1.0:
                continue  # Start price, not real market signal
            
            # Allow 1-bid listing ONLY as weak signal
            # Weight will be 0.35 (never dominant)
            weight = calculate_confidence_weight(bids, hours)
            price_samples.append({
                "price": float(current),
                "weight": weight,  # Already 0.35 from calculate_confidence_weight
                "bids": bids,
                "hours": hours,
                "reason": f"single_bid_weak_signal_{price_ratio*100:.0f}pct",
                "is_weak_signal": True  # Mark for observability
            })
            continue
        
        is_real, reason = is_realistic_auction_price(current, bids, hours, reference_price, True)
        
        if not is_real:
            continue
        
        weight = calculate_confidence_weight(bids, hours)
        price_samples.append({
            "price": float(current), 
            "weight": weight, 
            "bids": bids, 
            "hours": hours,
            "reason": reason
        })
    
    # REVISED: Accept high-quality single samples
    if not price_samples:
        return None
    
    # Track excluded listings for observability
    excluded_listings = []
    
    # SINGLE SAMPLE: Strict quality gates
    if len(price_samples) == 1:
        sample = price_samples[0]
        price_ratio = sample["price"] / reference_price if reference_price > 0 else 0
        
        # CRITICAL: Reject single 1-bid samples (too weak)
        if sample["bids"] == 1:
            # Single 1-bid listing = weak signal only, not market truth
            return None  # Force fallback to web search or skip
        
        # Quality gates for single sample (≥3 bids required)
        if sample["bids"] >= 3 and price_ratio >= 0.35:
            # High-quality single auction: real bidding momentum
            # Apply conservative discount by bid count
            if sample["bids"] >= 5:
                discount = 0.92
            elif sample["bids"] >= 3:
                discount = 0.90
            else:
                discount = 0.88
            
            resale_price = sample["price"] * discount
            confidence = 0.50 + (min(sample["bids"], 20) / 20) * 0.15  # 0.50-0.65 range
            
            if sanity_reference:
                resale_price = apply_global_sanity_check(resale_price, sanity_reference, False, "single_high_quality")
            
            return {
                "resale_price": round(resale_price, 2),
                "market_value": round(sample["price"], 2),
                "source": "single_high_quality_auction",
                "sample_size": 1,
                "market_based": True,
                "buy_now_ceiling": buy_now_ceiling,
                "confidence": round(confidence, 2),
                "bids_distribution": [sample["bids"]],
                "price_distribution": [sample["price"]],
                "excluded_listings": excluded_listings,
                "validation": {
                    "bids_check": "PASS (≥3)",
                    "price_check": f"PASS (>={price_ratio*100:.0f}%)",
                    "momentum_check": "PASS",
                    "discount_applied": f"{discount*100:.0f}%"
                }
            }
        
        # Low-quality single sample: reject
        return None
    
    # MULTI-SAMPLE: Remove low outliers if we have enough samples
    if len(price_samples) >= 3:
        prices = [s["price"] for s in price_samples]
        max_price = max(prices)
        
        filtered_samples = []
        for sample in price_samples:
            if sample["price"] >= max_price * 0.30:  # Keep if ≥30% of max
                filtered_samples.append(sample)
            else:
                excluded_listings.append({
                    "price": sample["price"],
                    "bids": sample["bids"],
                    "reason": "low_outlier (<30% of max)"
                })
        
        if filtered_samples:  # Use filtered if we still have samples
            price_samples = filtered_samples
    
    market_value = weighted_median(price_samples)
    
    # Determine discount based on MAXIMUM bid count (not average)
    max_bids = max(s.get("bids", 0) for s in price_samples)
    has_weak_signals = any(s.get("is_weak_signal", False) for s in price_samples)
    
    # Conservative discount by bid count
    if max_bids >= 5:
        resale_pct, source = 0.92, "auction_demand_high_activity"
    elif max_bids >= 3:
        resale_pct, source = 0.90, "auction_demand_moderate"
    elif max_bids == 2:
        resale_pct, source = 0.88, "auction_demand_low"
    else:  # max_bids == 1
        resale_pct, source = 0.82, "auction_demand_weak_signals"
    
    # Additional penalty if weak signals are present
    if has_weak_signals and max_bids < 3:
        resale_pct *= 0.95  # Extra 5% discount for weak signal dominance
    
    resale_price = market_value * resale_pct
    
    if buy_now_ceiling and buy_now_ceiling > market_value and resale_price > buy_now_ceiling * 0.95:
        resale_price = buy_now_ceiling * 0.95
    
    if sanity_reference:
        resale_price = apply_global_sanity_check(resale_price, sanity_reference, False, source)
    
    # Calculate confidence with strict 1-bid penalty
    max_bids = max(s["bids"] for s in price_samples)
    weak_signal_count = sum(1 for s in price_samples if s.get("is_weak_signal", False))
    
    sample_factor = min(len(price_samples) / 4, 1.0)  # 1 sample=0.25, 4+=1.0
    bid_factor = min(max_bids / 10, 1.0)  # 10+ bids=1.0
    
    # Base confidence
    confidence = 0.50 + (sample_factor * 0.25) + (bid_factor * 0.15)
    
    # CRITICAL: Cap confidence contribution from 1-bid listings
    if weak_signal_count > 0:
        # Each 1-bid listing contributes at most +0.10 to confidence
        weak_signal_bonus = min(weak_signal_count * 0.05, 0.10)
        # If weak signals dominate, cap confidence at 0.60
        if weak_signal_count >= len(price_samples) / 2:
            confidence = min(confidence, 0.60)
    
    confidence = min(0.90, confidence)  # Cap at 0.90 (never 100% certain)
    
    # Enhanced observability for 1-bid handling
    weak_signal_listings = [
        {
            "price": s["price"],
            "bids": s["bids"],
            "weight": s["weight"],
            "reason": s["reason"]
        }
        for s in price_samples if s.get("is_weak_signal", False)
    ]
    
    return {
        "resale_price": round(resale_price, 2),
        "market_value": round(market_value, 2),
        "source": source,
        "sample_size": len(price_samples),
        "market_based": True,
        "buy_now_ceiling": buy_now_ceiling,
        "confidence": round(confidence, 2),
        # Enhanced observability
        "bids_distribution": [s["bids"] for s in price_samples],
        "price_distribution": [round(s["price"], 2) for s in price_samples],
        "excluded_listings": excluded_listings,
        "weak_signal_listings": weak_signal_listings,  # NEW: Track 1-bid listings
        "validation": {
            "min_bids_met": all(s["bids"] >= 1 for s in price_samples),
            "outliers_removed": len(excluded_listings),
            "weak_signals_count": len(weak_signal_listings),
            "max_bids": max_bids,
            "discount_applied": f"{resale_pct*100:.0f}%",
            "sample_quality": "high" if confidence >= 0.70 else ("moderate" if confidence >= 0.55 else "low")
        }
    }


def calculate_all_market_resale_prices(listings: List[Dict[str, Any]], variant_new_prices: Optional[Dict[str, float]] = None, unrealistic_floor: float = 10.0, typical_multiplier: float = 5.0, context=None, ua: str = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    variant_keys = set(l.get("variant_key") for l in listings if l.get("variant_key"))
    variant_new_prices = variant_new_prices or {}
    reference_price = _get_new_price_estimate(query_analysis)
    
    if query_analysis:
        unrealistic_floor = _get_min_realistic_price(query_analysis)
    
    results = {}
    for vk in variant_keys:
        variant_new = variant_new_prices.get(vk)
        market_data = calculate_market_resale_from_listings(vk, listings, reference_price, unrealistic_floor, context, ua, variant_new)
        if market_data:
            results[vk] = market_data
            print(f"   📊 Market: {vk} = {market_data['resale_price']} CHF ({market_data['source']})")
    
    return results
# ==============================================================================
# VARIANT INFO BATCH FETCHING (v7.0 - with REAL web search!)
# ==============================================================================

def fetch_variant_info_batch(variant_keys: List[str], car_model: str = DEFAULT_CAR_MODEL, market_prices: Optional[Dict[str, Dict[str, Any]]] = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    """
    v7.0: Fetches variant info with REAL web search for new prices!
    
    Priority:
    1. Market prices (from Ricardo auctions)
    2. Web search (from Digitec/Galaxus) ← NEW in v7.0!
    3. AI estimate (fallback)
    """
    if not variant_keys:
        return {}
    
    variant_keys = [vk for vk in variant_keys if vk is not None]
    if not variant_keys:
        return {}
    
    market_prices = market_prices or {}
    results = {}
    need_new_price = []
    category = _get_category(query_analysis)
    resale_rate = _get_resale_rate(query_analysis)
    
    # First pass: handle variants with market data
    for vk in variant_keys:
        if vk in market_prices:
            market_data = market_prices[vk]
            cached = get_cached_variant_info(vk)
            # v9.0 FIX: Use market_based from market_data, not hardcoded True!
            # single_sample_buy_now_fallback returns market_based=False
            results[vk] = {
                "new_price": cached.get("new_price") if cached else None,
                "transport_car": cached.get("transport_car", True) if cached else True,
                "resale_price": market_data["resale_price"],
                "market_based": market_data.get("market_based", True),
                "market_source": market_data["source"],
                "market_sample_size": market_data["sample_size"],
                "market_value": market_data.get("market_value"),
                "buy_now_ceiling": market_data.get("buy_now_ceiling"),
            }
            # OPTIMIZATION: Skip websearch if market data has high confidence
            market_sample_size = market_data.get("sample_size", 0)
            market_based_resale = market_data.get("market_based", False)
            market_confidence_high = (market_sample_size > 0 and market_sample_size >= 10 and market_based_resale)
            
            if results[vk]["new_price"] is None:
                if market_confidence_high:
                    # High confidence market data (≥10 samples + market_based), AI estimate is good enough for new_price
                    print(f"   High confidence market ({market_sample_size} samples), skipping websearch for {vk[:40]}...")
                    # Will use AI estimate later (fallback path)
                else:
                    need_new_price.append(vk)
            continue
        
        # Check cache
        cached = get_cached_variant_info(vk)
        if cached and cached.get("resale_price"):
            results[vk] = {
                "new_price": cached["new_price"],
                "transport_car": cached["transport_car"],
                "resale_price": cached["resale_price"],
                "market_based": cached.get("market_based", False),
                "market_sample_size": cached.get("market_sample_size", 0),
            }
            continue

        need_new_price.append(vk)

    # v7.3: Use BATCH web search to avoid rate limits!
    if need_new_price:
        # IMPROVEMENT #3: Confidence-based websearch gating (TEST MODE ONLY)
        # Skip websearch for high-confidence extractions in test mode to save costs
        try:
            from runtime_mode import get_mode_config, is_budget_exceeded as mode_budget_check, should_use_websearch
            from config import load_config
            cfg = load_config()
            mode_config = get_mode_config(cfg.runtime.mode)

            # In TEST mode, skip websearch for high-confidence products
            if mode_config.mode.value == "test":
                # Filter out high-confidence products (they can use AI fallback)
                # (This would need to be passed from extraction, for now skip this optimization)
                # TODO: Pass extraction confidence through the pipeline
                low_confidence_need_web = []

                for vk in need_new_price:
                    # Check if this variant has high extraction confidence
                    # (This would need to be passed from extraction, for now skip this optimization)
                    # TODO: Pass extraction confidence through the pipeline
                    low_confidence_need_web.append(vk)

                need_new_price = low_confidence_need_web
                if low_confidence_need_web:
                    print(f"   TEST MODE: Skipped websearch for {len(low_confidence_need_web)} high-confidence products")
        except ImportError:
            pass  # runtime_mode not available, proceed normally

        if need_new_price:
            # OPTIMIZATION: Skip websearch for commodity/stable-price variants
            commodity_variants = []
            websearch_variants = []
            
            for vk in need_new_price:
                # Use variant_key as websearch_query (in real pipeline, this would be display_name/final_search_name)
                # TODO: Pass websearch_query metadata from main.py for more accurate detection
                if is_commodity_variant(vk, category, websearch_query=vk):
                    commodity_variants.append(vk)
                else:
                    websearch_variants.append(vk)
            
            if commodity_variants:
                print(f"   Skipping websearch for {len(commodity_variants)} commodity variants (stable prices)")
            
            if websearch_variants:
                print(f"\n   BATCH web searching {len(websearch_variants)} variants (rate-limit safe)...")

                # v7.3.3: Pass query_analysis for better search term cleaning
                web_results = search_web_batch_for_new_prices(websearch_variants, category, query_analysis)
            else:
                web_results = {}

        for vk in need_new_price:
            web_result = web_results.get(vk)

            if web_result and web_result.get("new_price"):
                new_price = web_result["new_price"]
                price_source = web_result.get("price_source", PRICE_SOURCE_WEB_SINGLE)
                
                # Calculate resale with sanity checks
                resale_price = new_price * resale_rate
                max_resale = new_price * MAX_RESALE_PERCENT_OF_NEW
                if resale_price > max_resale:
                    resale_price = max_resale
                
                # CRITICAL: Resale can never exceed new price
                if resale_price > new_price * 0.95:
                    resale_price = new_price * 0.85
                
                if vk in results:
                    # Already has market data, just add new_price
                    results[vk]["new_price"] = new_price
                    results[vk]["price_source"] = price_source
                else:
                    results[vk] = {
                        "new_price": new_price,
                        "transport_car": True,
                        "resale_price": resale_price,
                        "market_based": False,
                        "market_sample_size": 0,
                        "price_source": price_source,
                    }
                
                # Cache it
                set_cached_variant_info(vk, new_price, True, resale_price, False, 0)
            else:
                # No web result, will use AI fallback
                if vk not in results:
                    results[vk] = {
                        "new_price": None,
                        "transport_car": True,
                        "resale_price": None,
                        "market_based": False,
                        "market_sample_size": 0,
                    }
    
    # Final pass: AI estimation for variants still missing prices
    need_ai = [vk for vk in variant_keys if vk in results and results[vk].get("new_price") is None]
    
    if need_ai:
        # 🧪 TEST MODE: Skip AI fallback to save costs
        try:
            from config import load_config
            from runtime_mode import get_mode_config
            cfg = load_config()
            mode_config = get_mode_config(cfg.runtime.mode)
            
            if mode_config.mode.value == "test":
                print(f"   🧪 TEST MODE: Skipping AI fallback for {len(need_ai)} variants (would cost ${len(need_ai) * 0.003:.3f})")
                # Mark as no_price instead of using AI
                for vk in need_ai:
                    if vk in results:
                        results[vk]["price_source"] = "no_price"
                return results
        except ImportError:
            pass
        
        print(f"   🤖 AI fallback for {len(need_ai)} variants...")
        ai_results = _fetch_variant_info_from_ai_batch(need_ai, car_model, market_prices, query_analysis)
        
        for vk, info in ai_results.items():
            if vk in results:
                if results[vk].get("new_price") is None:
                    results[vk]["new_price"] = info.get("new_price")
                    results[vk]["price_source"] = PRICE_SOURCE_AI_ESTIMATE
            else:
                results[vk] = info
    
    return results


def _fetch_variant_info_from_ai_batch(variant_keys: List[str], car_model: str = DEFAULT_CAR_MODEL, market_prices: Optional[Dict[str, Dict[str, Any]]] = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    """AI-based variant info estimation (fallback when web search fails)."""
    if not variant_keys or is_budget_exceeded():
        return {}
    
    market_prices = market_prices or {}
    resale_rate = _get_resale_rate(query_analysis)
    min_realistic = _get_min_realistic_price(query_analysis)
    category = _get_category(query_analysis)

    # v7.2.1: Remove pipe from variant keys for cleaner AI prompt
    clean_variant_keys = [vk.replace("|", " ") for vk in variant_keys]
    
    prompt = f"""Du bist Preisexperte für ricardo.ch (SCHWEIZ).

KATEGORIE: {category}
MINDESTPREIS: {min_realistic} CHF

Analysiere diese Produkte und schätze:
1. AKTUELLER Schweizer Neupreis (nicht historischer UVP!)
2. Realistischer Wiederverkaufspreis (gebraucht)
3. Passt in {car_model}?

REGELN:
- Elektronik: Berücksichtige Alter (3+ Jahre = stark reduziert)
- Fitness/Gewichte: Gusseisen = 1.5-2 CHF/kg, Bumper = 2.5-3.5 CHF/kg
- Kleidung: Tommy Hilfiger Pullover ~120-150 CHF neu

PRODUKTE:
{chr(10).join(f"- {cvk}" for cvk in clean_variant_keys)}

Antworte NUR als JSON:
{{"Produkt Variante": {{"new_price": X, "resale_price": X, "transport": true/false}}, ...}}"""

    results = {}
    try:
        raw = call_ai(prompt, max_tokens=1500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                for vk in variant_keys:
                    info = parsed.get(vk)
                    if not info:
                        for key, val in parsed.items():
                            if key.lower() in vk.lower() or vk.lower() in key.lower():
                                info = val
                                break
                    
                    if info:
                        try:
                            if isinstance(info, dict):
                                new_price = float(info.get("new_price", 0))
                                resale_price = float(info.get("resale_price", 0))
                                transport = bool(info.get("transport", True))
                            else:
                                new_price = float(info)
                                resale_price = new_price * resale_rate
                                transport = True
                            
                            if new_price < min_realistic * 2:
                                continue
                            
                            if resale_price > new_price * MAX_RESALE_PERCENT_OF_NEW:
                                resale_price = new_price * resale_rate
                            
                            # Weight validation
                            if is_weight_plate(vk):
                                validated_resale, _ = validate_weight_price(vk, resale_price, is_resale=True)
                                validated_new, _ = validate_weight_price(vk, new_price, is_resale=False)
                                new_price = validated_new
                                resale_price = validated_resale
                            
                            # v7.3.2: Apply model-year adjustment for old electronics
                            if category == "electronics":
                                new_price = _adjust_price_for_model_year(vk, new_price, category)
                                resale_price = new_price * _get_component_resale_rate(vk, category, resale_rate)
                            
                            if new_price > 0:
                                results[vk] = {
                                    "new_price": new_price,
                                    "transport_car": transport,
                                    "resale_price": resale_price if resale_price > 0 else new_price * resale_rate,
                                    "market_based": False,
                                    "market_sample_size": 0,
                                    "price_source": PRICE_SOURCE_AI_ESTIMATE,
                                }
                                set_cached_variant_info(vk, new_price, transport, resale_price, False, 0)
                        except:
                            pass
    except Exception as e:
        print(f"⚠️ AI variant query failed: {e}")
    
    return results


# ==============================================================================
# SEARCH TERM EXTRACTION
# ==============================================================================

def extract_clean_search_terms(product_name: str, category: str = "unknown") -> Dict[str, Any]:
    """Extract clean search terms from product name for web search."""
    # Remove common noise words
    noise_words = ["neu", "new", "original", "ovp", "top", "super", "mega", "wow", "!!!", "???"]
    
    # Clean the name
    clean = product_name.lower()
    for noise in noise_words:
        clean = clean.replace(noise.lower(), "")
    
    # Split into words
    words = [w.strip() for w in clean.split() if len(w.strip()) > 2]
    
    # Build search terms (first 4 meaningful words)
    search_terms = words[:4] if words else [product_name]
    
    return {
        "search_terms": search_terms,
        "clean_name": " ".join(words),
        "category": category,
    }

# ==============================================================================
# BUNDLE DETECTION & PRICING
# ==============================================================================

BUNDLE_KEYWORDS = [
    "set", "paket", "bundle", "lot", "konvolut", "sammlung",
    "2x", "3x", "4x", "5x", "6x", "10x", "paar", "stück",
    "inkl", "inklusive", "mit", "plus", "und", "&",
]

def looks_like_bundle(title: str, description: str = "") -> bool:
    """Quick check if listing might be a bundle."""
    text = f"{title} {description}".lower()
    
    # v9.0 FIX: "2 Stk. à 2.5kg" = Quantity, NOT bundle!
    # Pattern: Zahl + Stk + à/x/@ + Gewicht = single product with quantity
    if re.search(r'\d+\s*stk\.?\s*[àax@]\s*\d+', text):
        return False
    
    # Check for real bundle keywords
    for kw in BUNDLE_KEYWORDS:
        if kw in text:
            # But exclude "stück/stk" if it's just quantity notation
            if kw in ["stück", "stk"] and not re.search(r'\d+\s*(stück|stk)\s+\w+', text):
                continue  # Skip - it's just "2 Stk." quantity
            return True
    
    # Quantity pattern - but only for real bundles with multiple items
    qty_pattern = r'\b(\d+)\s*(x|pcs|pieces?)\b'  # Removed stück/stk - handled above
    if re.search(qty_pattern, text):
        return True
    
    return False

def detect_bundle_with_ai(
    title: str,
    description: str,
    query: str,
    image_url: Optional[str] = None,
    use_vision: bool = False,
    query_analysis: Optional[Dict] = None,
    batch_result: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Detect if listing is a bundle and identify components.
    
    v7.3.4: Can use pre-computed batch_result to avoid redundant AI calls.
    """
    result = {
        "is_bundle": False,
        "components": [],
        "confidence": 0.0,
    }
    
    # v7.3.4: Use batch result if available (cost optimization!)
    if batch_result is not None:
        return batch_result
    
    if not looks_like_bundle(title, description):
        return result
    
    # Fallback: Individual detection (only if batch wasn't used)
    prompt = f"""Analyze this Ricardo listing for bundle/set:

TITLE: {title}
DESCRIPTION: {description[:500] if description else "None"}
SEARCH TERM: {query}

Is this a bundle/set with multiple items?

If YES, list the components with estimated quantity.

Respond ONLY as JSON:
{{
  "is_bundle": true/false,
  "components": [
    {{"name": "Item 1", "quantity": 2, "unit": "pieces"}},
    {{"name": "Item 2", "quantity": 1, "unit": "pieces"}}
  ],
  "confidence": 0.0-1.0
}}"""

    try:
        raw = call_ai(prompt, max_tokens=500)
        if raw:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group(0))
                add_cost(COST_CLAUDE_HAIKU)
                
                result["is_bundle"] = parsed.get("is_bundle", False)
                result["components"] = parsed.get("components", [])
                result["confidence"] = parsed.get("confidence", 0.5)
    except Exception as e:
        pass  # Return default result on error
    
    return result


def price_bundle_components(
    components: List[Dict[str, Any]],
    base_product: str,
    context=None,
    ua: str = None,
    query_analysis: Optional[Dict] = None,
    pre_fetched_prices: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Price individual bundle components with smart estimation.
    
    v7.4: Uses PRE-FETCHED prices from PRICE_FETCHING phase (OBJECTIVE B)
    - No web search during evaluation (cost optimization!)
    - Falls back to AI estimation if price not available
    - Pre-fetched prices come from fetch_variant_info_batch()
    
    Example: "Olympiastange + 3× Kurzhantel + 2× 5kg Gusseisen"
    → Uses prices fetched in PRICE_FETCHING phase
    → Much more accurate than AI guessing!
    """
    priced = []
    resale_rate = _get_resale_rate(query_analysis)
    category = _get_category(query_analysis)

    # Use pre-fetched prices from PRICE_FETCHING phase
    web_prices = pre_fetched_prices or {}
    
    for comp in components:
        name = comp.get("name", "Unknown")
        qty = comp.get("quantity") or 1
        if not isinstance(qty, (int, float)):
            try:
                qty = int(qty)
            except:
                qty = 1
        
        # Try pre-fetched price first
        web_result = web_prices.get(name)
        if web_result and web_result.get("new_price"):
            est_new = web_result["new_price"]
            price_source = PRICE_SOURCE_WEB_SINGLE  # Pre-fetched from web search
            print(f"      {name}: {est_new} CHF (pre-fetched)")
        else:
            # Fallback: AI estimation
            est_new = _estimate_component_price(name, category, query_analysis)
            est_new = _adjust_price_for_model_year(name, est_new, category)
            price_source = PRICE_SOURCE_AI_ESTIMATE
            print(f"      {name}: {est_new} CHF (AI fallback)")
        
        # Guard: Skip component if price estimation failed
        if est_new is None or est_new <= 0:
            print(f"      ⚠️ {name}: Price unavailable, skipping component")
            continue
        
        # GUARD: Skip component if price is unrealistic (likely misidentification)
        if est_new > MAX_COMPONENT_PRICE:
            print(f"      ⚠️ {name}: Price {est_new:.2f} CHF exceeds max ({MAX_COMPONENT_PRICE:.2f}), skipping component")
            continue
        
        # Calculate resale with category-aware rate
        component_resale_rate = _get_component_resale_rate(name, category, resale_rate)
        est_resale = est_new * component_resale_rate
        
        priced.append({
            "name": name,
            "quantity": qty,
            "new_price_each": round(est_new, 2),
            "resale_price_each": round(est_resale, 2),
            "total_new": round(est_new * qty, 2),
            "total_resale": round(est_resale * qty, 2),
            "price_source": price_source,
        })
    
    return priced


def _estimate_component_price(name: str, category: str, query_analysis: Optional[Dict] = None) -> float:
    """
    v7.3.3: Improved component price estimation.
    Uses weight-based pricing for fitness, smart defaults for other categories.
    GOAL: Avoid unrealistic 50 CHF defaults!
    """
    name_lower = name.lower()
    
    # ACCESSORIES (low value items) - handle first
    # Expanded map for better accuracy
    ACCESSORY_KEYWORDS = {
        # Cases and bags
        "koffer": 15.0, "case": 15.0, "tasche": 15.0, "bag": 15.0, "etui": 15.0,
        "hülle": 15.0, "cover": 15.0, "schutzhülle": 15.0,
        # Small accessories
        "adapter": 10.0, "clip": 10.0, "halter": 10.0, "holder": 10.0,
        # Cables and chargers
        "kabel": 20.0, "cable": 20.0, "ladegerät": 20.0, "charger": 20.0, "ladekabel": 20.0,
        # Bands and straps
        "armband": 25.0, "band": 25.0, "strap": 25.0, "wristband": 25.0,
        # Manuals (no value)
        "anleitung": 0.0, "manual": 0.0, "handbuch": 0.0,
    }
    
    for keyword, price in ACCESSORY_KEYWORDS.items():
        if keyword in name_lower:
            return price
    
    # FITNESS: Weight-based pricing (CHF per kg)
    if category == "fitness" or any(kw in name_lower for kw in WEIGHT_PLATE_KEYWORDS):
        weight_kg = extract_weight_kg(name)
        if weight_kg and weight_kg > 0:
            weight_type = get_weight_type(name)
            pricing = WEIGHT_PRICING.get(weight_type, WEIGHT_PRICING["standard"])
            # v9.0: Calibrated plates are more expensive!
            if weight_type == "calibrated":
                return weight_kg * pricing["new_price_per_kg"] * 1.5
            # v7.3.3: Use realistic CHF/kg pricing
            return weight_kg * pricing["new_price_per_kg"]
        
        # v7.3.3: Try to extract weight from quantity patterns like "4x 5kg"
        import re
        qty_weight = re.search(r'(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*kg', name_lower)
        if qty_weight:
            qty = int(qty_weight.group(1))
            per_kg = float(qty_weight.group(2).replace(',', '.'))
            total_kg = qty * per_kg
            return total_kg * 3.5  # Standard ~3.5 CHF/kg
        
        # Fitness equipment defaults (no weight found)
        if any(kw in name_lower for kw in ["hantelscheibe", "gewicht", "plate", "scheibe"]):
            # v9.0: "Hantelscheibe" ohne Gewicht ist UNGÜLTIG - return None für Fehlerbehandlung
            return None
        if any(kw in name_lower for kw in ["hantelstange", "langhantel", "barbell", "stange"]):
            return 80.0
        if any(kw in name_lower for kw in ["kurzhantel", "dumbbell", "gymnastikhantel"]):
            return 15.0  # Small dumbbells
        if any(kw in name_lower for kw in ["bank", "bench", "rack"]):
            return 150.0
        if any(kw in name_lower for kw in ["ständer", "halterung", "stand"]):
            return 60.0
        if any(kw in name_lower for kw in ["set", "kit"]):
            return 80.0  # Generic set
        return 40.0  # Generic fitness default (was 50)
    
    # ELECTRONICS: Model-specific pricing
    if category == "electronics":
        # Garmin smartwatches
        if "forerunner" in name_lower:
            if any(m in name_lower for m in ["965", "955", "945"]):
                return 500.0
            if any(m in name_lower for m in ["935", "735", "645"]):
                return 200.0  # Older models
            return 300.0
        if "fenix" in name_lower:
            if "7" in name_lower or "8" in name_lower:
                return 600.0
            if "6" in name_lower:
                return 400.0
            if "5" in name_lower:
                return 250.0  # 2017 model
            return 400.0
        if "vivofit" in name_lower:
            return 80.0
        if "vivoactive" in name_lower:
            return 250.0
        if "brustgurt" in name_lower or "heart rate" in name_lower:
            return 50.0
        if "armband" in name_lower or "band" in name_lower:
            return 25.0
        if "ladekabel" in name_lower or "charger" in name_lower:
            return 20.0
        return 100.0  # Generic electronics default
    
    # CLOTHING
    if category == "clothing":
        if any(kw in name_lower for kw in ["jacke", "jacket", "mantel", "coat"]):
            return 150.0
        if any(kw in name_lower for kw in ["hose", "jeans", "pants"]):
            return 80.0
        if any(kw in name_lower for kw in ["pullover", "sweater", "hoodie"]):
            return 90.0
        if any(kw in name_lower for kw in ["hemd", "shirt", "bluse"]):
            return 70.0
        return 60.0  # Generic clothing default
    
    # DEFAULT for unknown categories
    return 50.0


def _adjust_price_for_model_year(name: str, price: float, category: str) -> float:
    """
    Adjust price based on detected model year (for electronics).
    Older models should have lower new prices.
    """
    if category != "electronics":
        return price
    
    name_lower = name.lower()
    
    # Garmin Fenix series (detect model generation)
    if "fenix" in name_lower:
        if "5" in name_lower:  # 2017 model
            return min(price, 250.0)
        if "6" in name_lower:  # 2019 model
            return min(price, 450.0)
        if "7" in name_lower:  # 2022 model
            return min(price, 650.0)
    
    # Garmin Forerunner series
    if "forerunner" in name_lower:
        if any(m in name_lower for m in ["235", "230", "220"]):  # Old models
            return min(price, 150.0)
        if any(m in name_lower for m in ["935", "735"]):  # 2017-2018
            return min(price, 200.0)
        if any(m in name_lower for m in ["945", "745"]):  # 2019-2020
            return min(price, 350.0)
    
    return price


def _get_component_resale_rate(name: str, category: str, default_rate: float) -> float:
    """
    Get resale rate for a specific component type.
    Accessories have lower resale, main items higher.
    """
    name_lower = name.lower()
    
    # Accessories have lower resale value
    if any(kw in name_lower for kw in ["armband", "band", "kabel", "cable", "charger", "adapter"]):
        return 0.30  # Accessories: 30%
    
    # Main fitness equipment holds value well
    if category == "fitness":
        if any(kw in name_lower for kw in ["hantelscheibe", "gewicht", "plate", "bumper"]):
            return 0.60  # Weight plates: 60%
        if any(kw in name_lower for kw in ["bank", "bench", "rack"]):
            return 0.50  # Benches/racks: 50%
    
    # Electronics depreciate based on age
    if category == "electronics":
        if "fenix 5" in name_lower or "forerunner 935" in name_lower:
            return 0.55  # Older electronics: 55%
        if "fenix 6" in name_lower or "forerunner 945" in name_lower:
            return 0.50  # Mid-age: 50%
    
    return default_rate


def calculate_bundle_new_price(priced_components: List[Dict[str, Any]]) -> float:
    """Calculate total new price for bundle."""
    if not priced_components:
        return 0.0
    
    total = sum(c.get("total_new", 0) for c in priced_components)
    return round(total, 2)


def calculate_bundle_resale(priced_components: List[Dict[str, Any]], bundle_new_price: float) -> float:
    """Calculate bundle resale price with discount."""
    if not priced_components:
        return 0.0
    
    # Sum component resale prices
    component_total = sum(c.get("total_resale", 0) for c in priced_components)
    
    # Apply bundle discount (people pay less for bundles)
    bundle_resale = component_total * (1 - BUNDLE_DISCOUNT_PERCENT)
    
    # Cap at max percent of new price
    max_resale = bundle_new_price * MAX_BUNDLE_RESALE_PERCENT_OF_NEW
    if bundle_resale > max_resale:
        bundle_resale = max_resale
    
    return round(bundle_resale, 2)


# ==============================================================================
# PROFIT & STRATEGY
# ==============================================================================

def calculate_profit(resale_price: float, purchase_price: float) -> float:
    if resale_price <= 0 or purchase_price <= 0:
        return 0.0
    return round(resale_price * (1 - RICARDO_FEE_PERCENT) - purchase_price - SHIPPING_COST_CHF, 2)


def determine_strategy(expected_profit: float, is_auction: bool, has_buy_now: bool, bids_count: int = 0, hours_remaining: float = None, is_bundle: bool = False) -> Tuple[str, str]:
    profit = expected_profit or 0
    hours = hours_remaining if hours_remaining is not None else 999
    bids = bids_count or 0
    
    if profit < MIN_PROFIT_THRESHOLD:
        return ("skip", f"Profit {profit:.0f} CHF below minimum ({MIN_PROFIT_THRESHOLD:.0f})")
    if has_buy_now and profit >= 80:
        return ("buy_now", f"🔥 Buy now! Profit {profit:.0f} CHF")
    if has_buy_now and profit >= 40:
        return ("buy_now", f"Buy recommended, profit {profit:.0f} CHF")
    if is_auction:
        if bids >= 15:
            return ("watch", f"⚠️ Highly contested ({bids} bids)")
        if hours < 2 and profit >= 40:
            return ("bid_now", f"🔥 Ending soon! Max {profit:.0f} CHF profit possible")
        if hours < 6 and profit >= 30:
            return ("bid", f"Bid recommended, ends in {hours:.0f}h")
        if hours < 24 and profit >= 40:
            return ("bid", f"Bid today, profit {profit:.0f} CHF")
        if profit >= 60:
            return ("watch", f"Watch, good profit ({profit:.0f} CHF)")
        return ("watch", f"Watch, {hours:.0f}h remaining")
    if profit >= 30:
        return ("watch", f"Inquire, profit {profit:.0f} CHF")
    return ("watch", f"Watch, profit {profit:.0f} CHF")


def calculate_deal_score(expected_profit: float, purchase_price: float, resale_price: Optional[float], bids_count: Optional[int] = None, hours_remaining: Optional[float] = None, is_auction: bool = True, has_variant_key: bool = True, market_based_resale: bool = False, is_bundle: bool = False) -> float:
    """v6.8: Calculate deal score with reformed scoring."""
    score = 5.0
    profit = expected_profit or 0
    
    # Variant classification bonus/penalty
    if not has_variant_key:
        score -= 0.5  # Reduced from -2.0
    
    if market_based_resale:
        score += 1.0
    if is_bundle:
        score += 0.3
    
    # Margin-based scoring
    if resale_price and resale_price > 0 and purchase_price > 0:
        margin = (profit / purchase_price) * 100
        if margin > 100: score += 3.5
        elif margin > 50: score += 3.0
        elif margin > 30: score += 2.0
        elif margin > 15: score += 1.0
        elif margin > 0: score += 0.5
        elif margin > -10: score -= 0.5
        elif margin > -25: score -= 1.5
        else: score -= 2.5
    
    # Absolute profit bonus
    if profit > 500:
        score += 3.0
    elif profit > 200:
        score += 2.0
    elif profit > 100:
        score += 1.5
    elif profit > 50:
        score += 1.0
    
    # Auction timing
    if is_auction:
        hours = hours_remaining if hours_remaining is not None else 999
        bids = bids_count or 0
        
        if hours > 48: score -= 1.5
        elif hours > 24: score -= 1.0
        elif hours > 12: score -= 0.5
        elif hours < 2: score += 0.5
        
        # High bids = BONUS (not penalty!)
        if bids >= 20:
            score += 0.5
        elif bids >= 10:
            score += 0.3
    
    # Clamp score to 0-10 range
    return max(0.0, min(10.0, score))


# MAIN EVALUATION FUNCTION
# ==============================================================================

def evaluate_listing_with_ai(
    title: str,
    description: str,
    current_price: Optional[float],
    buy_now_price: Optional[float],
    image_url: Optional[str],
    query: str,
    variant_key: Optional[str] = None,
    variant_info: Optional[Dict[str, Any]] = None,
    bids_count: Optional[int] = None,
    hours_remaining: Optional[float] = None,
    base_product: str = "",
    context=None,
    ua: str = None,
    query_analysis: Optional[Dict] = None,
    batch_bundle_result: Optional[Dict] = None,
    variant_info_by_key: Optional[Dict[str, Dict]] = None,
    quantity: int = 1,
) -> Dict[str, Any]:
    """
    v7.0: Main evaluation function with Claude-based AI.
    
    Evaluates a Ricardo listing and returns:
    - is_relevant: Is this the main product (not accessory)?
    - deal_score: 0-10 score
    - new_price: New price (from web search or AI)
    - resale_price_est: Expected resale price
    - expected_profit: Calculated profit
    - recommended_strategy: buy_now/bid/watch/skip
    - etc.
    """
    result = {
        "is_relevant": True,
        "deal_score": 5.0,
        "new_price": None,
        "resale_price_est": None,
        "expected_profit": 0.0,
        "transport_car": True,
        "ai_notes": "",
        "predicted_final_price": None,
        "prediction_confidence": None,
        "is_bundle": False,
        "bundle_components": None,
        "resale_price_bundle": None,
        "recommended_strategy": "watch",
        "strategy_reason": "",
        "market_based_resale": False,
        "market_sample_size": 0,
        "market_value": None,
        "price_source": PRICE_SOURCE_UNKNOWN,
        "buy_now_ceiling": None,
        "market_source": None,  # Granular market source (auction_demand, etc.)
    }
    
    # SAFEGUARD 1: BUNDLES DISABLED (out of scope)
    if batch_bundle_result and batch_bundle_result.get("is_bundle"):
        result["is_bundle"] = True
        result["recommended_strategy"] = "skip"
        result["strategy_reason"] = "Bundles disabled (out of scope)"
        result["deal_score"] = 0.0
        return result
    
    # Get variant info
    if variant_info:
        result["new_price"] = variant_info.get("new_price")
        result["transport_car"] = variant_info.get("transport_car", True)
        result["market_based_resale"] = variant_info.get("market_based", False)
        result["market_sample_size"] = variant_info.get("market_sample_size", 0)
        result["market_value"] = variant_info.get("market_value")
        result["buy_now_ceiling"] = variant_info.get("buy_now_ceiling")
        result["price_source"] = variant_info.get("price_source", PRICE_SOURCE_UNKNOWN)
        result["market_source"] = variant_info.get("market_source")  # Granular market source (auction_demand, etc.)
        
        # PRICING TRUTH: Check for learned resale estimate first
        learned_resale = variant_info.get("learned_resale_estimate")  # From products.resale_estimate
        if learned_resale and learned_resale > 0:
            result["resale_price_est"] = learned_resale
            result["price_source"] = "learned_market"  # Highest trust source
            print(f"   Using learned resale estimate: {learned_resale:.2f} CHF (from price_history)")
        elif variant_info.get("resale_price"):
            result["resale_price_est"] = variant_info["resale_price"]
    
    # PHASE 4.1c: DISABLED buy_now_fallback (unreliable arbitrary multiplier)
    # If no learned resale estimate and no web/market data, we skip the deal
    # This prevents false positives from arbitrary pricing assumptions
    
    # SAFETY FALLBACK: Use current_bid as resale floor when market pricing fails
    # This ensures live bid data is used even when variant_key grouping fails
    if not result["resale_price_est"] and current_price and bids_count and bids_count > 0:
        # Current bid is guaranteed minimum resale price
        # Apply conservative multiplier based on time remaining and bid count
        hours = hours_remaining if hours_remaining else 999
        
        if hours < 1:
            multiplier = 1.05  # Ending very soon, minimal rise expected
        elif hours < 24:
            multiplier = 1.10  # Ending soon, moderate rise
        elif hours < 72:
            multiplier = 1.15  # Mid-stage, more room to grow
        else:
            multiplier = 1.20  # Early stage, significant room to grow
        
        # Bid count confidence boost
        if bids_count >= 50:
            multiplier += 0.10  # Very hot item
        elif bids_count >= 20:
            multiplier += 0.05  # Hot item
        elif bids_count >= 10:
            multiplier += 0.03  # Competitive
        
        floor_resale = current_price * multiplier
        result["resale_price_est"] = floor_resale
        result["price_source"] = "current_bid_floor"
        result["prediction_confidence"] = min(0.75, 0.50 + (bids_count / 100))
        
        print(f"   Using current bid as floor: {current_price:.2f} × {multiplier:.2f} = {floor_resale:.2f} CHF ({bids_count} bids, {hours:.1f}h remaining)")
    
    # PHASE 4.1c: AI estimate fallback (heavily discounted)
    resale_rate = _get_resale_rate(query_analysis)
    if not result["resale_price_est"] and result["new_price"] and result["new_price"] > 0:
        # AI estimates are unreliable - discount by 50% for safety
        ai_discount = 0.5
        result["resale_price_est"] = result["new_price"] * resale_rate * ai_discount
        if result["price_source"] == PRICE_SOURCE_AI_ESTIMATE:
            print(f"   AI estimate discounted 50%: {result['resale_price_est']:.2f} CHF (unreliable)")
    
    # PHASE 4.1c: HARD SANITY CAPS
    if result["resale_price_est"] and result["new_price"]:
        # Cap 1: Resale price ≤ 70% of new price (used items reality)
        max_resale = result["new_price"] * 0.70
        if result["resale_price_est"] > max_resale:
            print(f"   SANITY CAP: Resale {result['resale_price_est']:.2f} > 70% of new {result['new_price']:.2f}, capping to {max_resale:.2f}")
            result["resale_price_est"] = max_resale
    
    # OPTIMIZATION: Early exit for obvious unprofitable listings
    # SAFETY: Only if resale_price_est is HIGH CONFIDENCE
    if current_price and result.get("resale_price_est"):
        # Check if resale_price_est is high confidence
        high_confidence_resale = False
        
        # High confidence source 1: Market data with ≥10 samples
        market_source = result.get("market_source") or ""
        if market_source.startswith("auction_demand"):
            if result.get("market_sample_size", 0) >= 10:
                high_confidence_resale = True
        
        # High confidence source 2: Web-based pricing (median or single)
        if result.get("price_source") in [PRICE_SOURCE_WEB_MEDIAN, PRICE_SOURCE_WEB_SINGLE]:
            if result.get("new_price"):  # new_price exists, resale derived deterministically
                high_confidence_resale = True
        
        # Early exit only if high confidence AND obviously unprofitable
        if high_confidence_resale and current_price >= result["resale_price_est"] * 0.90:
            result["recommended_strategy"] = "skip"
            result["strategy_reason"] = "Current price too high (≥90% of resale, high confidence)"
            result["expected_profit"] = calculate_profit(result["resale_price_est"], current_price)
            result["deal_score"] = 0.0
            
            # Skip expensive AI estimation, use query baseline for new_price if missing
            if not result["new_price"]:
                result["new_price"] = _get_new_price_estimate(query_analysis)
                result["price_source"] = PRICE_SOURCE_QUERY_BASELINE
            
            print(f"   Early exit: obvious skip (current={current_price:.2f}, resale={result['resale_price_est']:.2f})")
            return result
    
    # v9.0 FIX: If we have resale_price but no new_price, estimate new_price
    # This ensures data consistency: prefer rough but realistic values over NULL/0
    if result["resale_price_est"] and not result["new_price"]:
        # TEST MODE CONTRACT: AI price estimation is NOT allowed in TEST mode
        try:
            from config import load_config
            from runtime_mode import get_mode_config
            cfg = load_config()
            mode_config = get_mode_config(cfg.runtime.mode)
            is_test_mode = (mode_config.mode.value == "test")
        except:
            is_test_mode = False
        
        if is_test_mode:
            # MODE_GUARD: Block AI price estimation in TEST mode
            print(f"\nMODE_GUARD:")
            print(f"  runtime_mode: test")
            print(f"  feature: ai_price_estimation")
            print(f"  allowed: false")
            print(f"  reason: TEST_MODE_AI_ESTIMATION_BLOCKED")
            print(f"   TEST MODE: Skipping AI price estimation (not allowed in TEST mode)")
            # Do NOT estimate new_price - let it remain None
            # query_baseline will be used later as final fallback
        else:
            # Reverse calculate: new_price = resale_price / resale_rate
            estimated_new = result["resale_price_est"] / resale_rate if resale_rate > 0 else result["resale_price_est"] * 2
            result["new_price"] = round(estimated_new, 2)
            if result["price_source"] == PRICE_SOURCE_UNKNOWN:
                result["price_source"] = PRICE_SOURCE_AI_ESTIMATE  # Estimated from resale
    
    # QUANTITY-AWARE RESALE: Apply quantity multiplication for single products
    # CRITICAL: This must happen AFTER unit resale is calculated but BEFORE profit calculation
    # Bundles handle quantity per-component, so we skip this for bundles
    # Example: resale_unit=10, quantity=5 → resale_total=50
    if quantity > 1 and result["resale_price_est"] and not result.get("is_bundle"):
        unit_resale = result["resale_price_est"]
        result["resale_price_est"] = round(unit_resale * quantity, 2)
    
    # Determine effective purchase price
    is_auction = current_price is not None and buy_now_price is None
    has_buy_now = buy_now_price is not None
    
    if has_buy_now:
        purchase_price = buy_now_price
    elif current_price:
        # Predict final auction price
        prediction = predict_final_auction_price(
            current_price=current_price,
            bids_count=bids_count or 0,
            hours_remaining=hours_remaining or 999,
            median_price=result.get("market_value"),
            new_price=result.get("new_price"),
            typical_multiplier=_get_auction_multiplier(query_analysis),
        )
        purchase_price = prediction["predicted_final_price"]
        result["predicted_final_price"] = prediction["predicted_final_price"]
        result["prediction_confidence"] = prediction["confidence"]
    else:
        purchase_price = 0
    
    # PHASE 4.1c: BUNDLES DISABLED (missing unit_value implementation)
    # Bundles show -87% margins due to missing per-component pricing
    # Re-enable after implementing bundle_items.unit_value
    bundles_disabled = True
    if BUNDLE_ENABLED and not bundles_disabled and looks_like_bundle(title, description):
        vision_for_this_call = random.random() < VISION_RATE if image_url else False
        
        # MODE_GUARD: Vision usage decision
        try:
            from config import load_config
            from runtime_mode import get_mode_config
            cfg = load_config()
            mode_config = get_mode_config(cfg.runtime.mode)
            runtime_mode = mode_config.mode.value
        except:
            runtime_mode = "unknown"
        
        print(f"\nMODE_GUARD:")
        print(f"  runtime_mode: {runtime_mode}")
        print(f"  feature: vision")
        print(f"  allowed: {str(vision_for_this_call).lower()}")
        print(f"  reason: {'VISION_ENABLED_RANDOM' if vision_for_this_call else 'VISION_DISABLED_RANDOM'}")
        
        bundle_result = detect_bundle_with_ai(
            title=title,
            description=description,
            query=query,
            image_url=image_url,
            use_vision=vision_for_this_call,
            query_analysis=query_analysis,
            batch_result=batch_bundle_result,
        )
        result["vision_used"] = vision_for_this_call
        
        if bundle_result.get("is_bundle"):
            result["is_bundle"] = True
            result["bundle_components"] = bundle_result.get("components", [])
            
            # Price components
            priced = price_bundle_components(
                components=result["bundle_components"],
                base_product=base_product or query,
                context=context,
                ua=ua,
                query_analysis=query_analysis,
                pre_fetched_prices=variant_info_by_key,
            )
            result["bundle_components"] = priced
            
            # GUARD: Require at least 2 priced components
            # Single-component "bundles" are false positives (e.g., "25x charger" = 1 product type)
            if len(priced) < 2:
                print(f"   ⚠️ Bundle has only {len(priced)} valid component(s) — treating as single product")
                result["is_bundle"] = False
                # Fall through to normal pricing (query_baseline or other sources)
            else:
                # Calculate bundle resale
                bundle_new = calculate_bundle_new_price(priced)
                bundle_resale = calculate_bundle_resale(priced, bundle_new)
                
                result["resale_price_bundle"] = bundle_resale
                result["resale_price_est"] = bundle_resale
                result["new_price"] = bundle_new
                result["price_source"] = PRICE_SOURCE_BUNDLE_AGGREGATE
    
    # FIX #1: QUERY BASELINE FALLBACK - Final safety net to prevent NULL/0 resale prices
    # If ALL price sources failed (web, AI, market, buy_now, bundle), use query baseline
    # This ensures data quality: prefer rough but realistic values over NULL/0
    if not result["resale_price_est"] or result["resale_price_est"] <= 0:
        baseline_new = _get_new_price_estimate(query_analysis)
        baseline_resale_rate = _get_resale_rate(query_analysis)
        
        # Apply quantity for single products (bundles already handled)
        if not result.get("is_bundle"):
            result["new_price"] = round(baseline_new, 2)
            result["resale_price_est"] = round(baseline_new * baseline_resale_rate * quantity, 2)
        else:
            # For bundles, use baseline without quantity multiplication
            result["new_price"] = round(baseline_new, 2)
            result["resale_price_est"] = round(baseline_new * baseline_resale_rate, 2)
        
        result["price_source"] = PRICE_SOURCE_QUERY_BASELINE
        print(f"   ⚠️ Query baseline fallback: new={result['new_price']:.2f}, resale={result['resale_price_est']:.2f} CHF")
    
    # Calculate profit
    if result["resale_price_est"] and purchase_price:
        result["expected_profit"] = calculate_profit(result["resale_price_est"], purchase_price)
    
    # SAFEGUARD 2: PROFIT MARGIN CAP (≤30% for Swiss market reality)
    if result["expected_profit"] and purchase_price and purchase_price > 0:
        profit_margin_pct = (result["expected_profit"] / purchase_price) * 100
        MAX_REALISTIC_MARGIN_PCT = 30.0  # Swiss second-hand market reality (reduced from 50%)
        
        if profit_margin_pct > MAX_REALISTIC_MARGIN_PCT:
            print(f"   🚫 MARGIN CAP: {profit_margin_pct:.1f}% margin exceeds realistic max ({MAX_REALISTIC_MARGIN_PCT:.0f}%) - marking as skip")
            result["recommended_strategy"] = "skip"
            result["strategy_reason"] = f"Unrealistic profit margin ({profit_margin_pct:.0f}% > {MAX_REALISTIC_MARGIN_PCT:.0f}%)"
            result["deal_score"] = 0.0
            result["expected_profit"] = 0.0  # Zero out unrealistic profit
            return result
    
    # SAFEGUARD 3: MINIMUM PROFIT THRESHOLD (10 CHF)
    MIN_PROFIT_CHF = 10.0
    if result["expected_profit"] and result["expected_profit"] < MIN_PROFIT_CHF:
        print(f"   ⚠️ MIN PROFIT: {result['expected_profit']:.2f} CHF below threshold ({MIN_PROFIT_CHF:.0f} CHF) - marking as skip")
        result["recommended_strategy"] = "skip"
        result["strategy_reason"] = f"Profit below minimum threshold ({result['expected_profit']:.2f} < {MIN_PROFIT_CHF:.0f} CHF)"
        result["deal_score"] = 0.0
        return result
    
    # Determine strategy
    strategy, reason = determine_strategy(
        expected_profit=result["expected_profit"],
        is_auction=is_auction,
        has_buy_now=has_buy_now,
        bids_count=bids_count,
        hours_remaining=hours_remaining,
        is_bundle=result["is_bundle"],
    )
    result["recommended_strategy"] = strategy
    result["strategy_reason"] = reason
    
    # Calculate deal score
    result["deal_score"] = calculate_deal_score(
        expected_profit=result["expected_profit"],
        purchase_price=purchase_price,
        resale_price=result["resale_price_est"],
        bids_count=bids_count,
        hours_remaining=hours_remaining,
        is_auction=is_auction,
        has_variant_key=variant_key is not None,
        market_based_resale=result["market_based_resale"],
        is_bundle=result["is_bundle"],
    )
    
    # PROBLEM 3: POPULATE MARKET ANALYTICS FIELDS - Ensure no NULL values
    # Always populate market_value, buy_now_ceiling, market_based_resale, market_sample_size
    
    # market_value: Use resale_price_est as market value if not already set
    if not result.get("market_value") and result.get("resale_price_est"):
        result["market_value"] = result["resale_price_est"]
    
    # buy_now_ceiling: 85% of resale price (max we'd pay in buy-now)
    if not result.get("buy_now_ceiling") and result.get("resale_price_est"):
        result["buy_now_ceiling"] = round(result["resale_price_est"] * 0.85, 2)
    
    # market_based_resale: True if price_source is web-based
    if result["price_source"].startswith("web_"):
        result["market_based_resale"] = True
    
    # market_sample_size: Set based on price_source if not already set
    if result["market_sample_size"] == 0:
        if result["price_source"] == PRICE_SOURCE_WEB_MEDIAN:
            # Already set from websearch, keep it
            pass
        elif result["price_source"].startswith("web_"):
            result["market_sample_size"] = 1
        else:
            # ai_estimate, query_baseline, buy_now_fallback
            result["market_sample_size"] = 0
    
    # OPTIMIZATION: Calculate price confidence (observability only, no DB writes)
    def get_price_confidence(price_source: str, market_sample_size: int, market_source: Optional[str]) -> float:
        """Calculate confidence score for price estimate (0.0-1.0)."""
        if price_source == PRICE_SOURCE_WEB_MEDIAN:
            return 0.85
        elif price_source == PRICE_SOURCE_WEB_SINGLE:
            return 0.70
        elif market_source and market_source.startswith("auction_demand"):
            if market_sample_size >= 10:
                return 0.95
            elif market_sample_size >= 5:
                return 0.80
            elif market_sample_size >= 2:
                return 0.60
            else:
                return 0.50
        elif price_source == PRICE_SOURCE_AI_ESTIMATE:
            return 0.50
        elif price_source == PRICE_SOURCE_QUERY_BASELINE:
            return 0.30
        elif price_source == PRICE_SOURCE_BUY_NOW_FALLBACK:
            return 0.40
        elif price_source == PRICE_SOURCE_BUNDLE_AGGREGATE:
            return 0.65
        else:
            return 0.50
    
    price_confidence = get_price_confidence(
        result["price_source"],
        result.get("market_sample_size", 0),
        result.get("market_source")
    )
    
    # OBSERVABILITY: Append confidence to strategy_reason (no behavior change)
    if price_confidence < 0.60:
        result["strategy_reason"] += f" [conf: {price_confidence:.2f}]"
    
    # Build AI notes
    notes = []
    if result["market_based_resale"]:
        notes.append(f"📈 Market ({result['market_sample_size']} samples)")
    if result["is_bundle"]:
        notes.append(f"📦 Bundle ({len(result.get('bundle_components', []))} items)")
    if result["price_source"].startswith("web_"):
        notes.append(f"🌐 Web price ({result['price_source']})")
    notes.append(f"Strategy: {strategy}")
    result["ai_notes"] = " | ".join(notes)
    
    return result


# ==============================================================================
# VISION ANALYSIS FOR UNCLEAR LISTINGS
# ==============================================================================

def analyze_listing_with_vision(
    title: str,
    description: str,
    image_url: str,
    category: str = None,
) -> Dict[str, Any]:
    """
    Analyzes an unclear listing using vision to extract missing product information.
    
    Used when title and description don't provide enough clarity to identify the product.
    
    Args:
        title: Original listing title
        description: Listing description (may be vague)
        image_url: URL to product image
        category: Optional category path
    
    Returns:
        Dict with extracted product info
    """
    result = {
        "product_type": None,
        "brand": None,
        "model": None,
        "specifications": {},
        "condition": None,
        "is_bundle": False,
        "bundle_items": [],
        "confidence": 0.0,
        "notes": None,
        "vision_used": True,
        "success": False,
    }
    
    if not image_url:
        result["notes"] = "No image URL provided"
        return result
    
    # Build context from known info
    context_parts = []
    if title:
        context_parts.append(f"Titel: {title}")
    if description:
        desc_preview = description[:300] + "..." if len(description) > 300 else description
        context_parts.append(f"Beschreibung: {desc_preview}")
    if category:
        context_parts.append(f"Kategorie: {category}")
    
    context = "\n".join(context_parts) if context_parts else "Keine Kontextinformationen"
    
    prompt = f"""Du analysierst ein Produktbild von einem Online-Inserat um fehlende Informationen zu identifizieren.

BEKANNTE INFORMATIONEN:
{context}

DEINE AUFGABE:
Die vorhandenen Informationen sind zu vage. Analysiere das Bild und extrahiere:

1. **Produktidentifikation** - Um was handelt es sich genau? Marke? Modell?
2. **Spezifikationen** - Material, Gewicht/Grösse falls erkennbar
3. **Zustand** - neu/neuwertig/gebraucht
4. **Bundle/Set** - Falls mehrere Artikel sichtbar, liste sie auf

ANTWORTFORMAT (JSON):
{{
    "product_type": "z.B. Hantelscheiben, Smartwatch",
    "brand": "erkannte Marke oder null",
    "model": "erkanntes Modell oder null",
    "specifications": {{"weight_kg": null, "material": null}},
    "condition": "neu/neuwertig/gebraucht/unklar",
    "is_bundle": true/false,
    "bundle_items": ["Item 1", "Item 2"],
    "confidence": 0.0-1.0,
    "notes": "zusätzliche Beobachtungen"
}}

Antworte NUR mit dem JSON-Objekt."""

    try:
        response = _call_ai(
            prompt=prompt,
            max_tokens=800,
            image_url=image_url,
        )
        
        if response:
            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                parsed = json.loads(json_match.group())
                result.update(parsed)
                result["success"] = True
                result["vision_used"] = True
            else:
                result["notes"] = f"Could not parse JSON from response"
    except json.JSONDecodeError as e:
        result["notes"] = f"JSON parse error: {e}"
    except Exception as e:
        result["notes"] = f"Vision analysis error: {e}"
    
    return result


def batch_analyze_with_vision(
    listings: List[Dict[str, Any]],
    max_vision_calls: int = 5,
) -> List[Dict[str, Any]]:
    """
    Analyzes multiple unclear listings with vision.
    
    Args:
        listings: Listings that need vision analysis (must have 'image_urls' or 'image_url')
        max_vision_calls: Maximum number of vision API calls
    
    Returns:
        Same listings with added '_vision_result' field
    """
    to_analyze = [l for l in listings if l.get("image_urls") or l.get("image_url")][:max_vision_calls]
    
    if not to_analyze:
        print("   ⚠️ No listings with images for vision analysis")
        return listings
    
    print(f"\n👁️ Analyzing {len(to_analyze)} listings with vision...")
    
    for i, listing in enumerate(to_analyze, 1):
        title = listing.get("title", "")[:40]
        print(f"\n   [{i}/{len(to_analyze)}] {title}...")
        
        # Get first image URL
        image_urls = listing.get("image_urls", [])
        image_url = image_urls[0] if image_urls else listing.get("image_url")
        
        if not image_url:
            continue
        
        vision_result = analyze_listing_with_vision(
            title=listing.get("title", ""),
            description=listing.get("description", ""),
            image_url=image_url,
            category=listing.get("category_path"),
        )
        
        listing["_vision_result"] = vision_result
        listing["vision_used"] = True
        
        if vision_result.get("success"):
            # Update listing with extracted info
            if vision_result.get("product_type"):
                listing["_identified_product"] = vision_result["product_type"]
            if vision_result.get("brand"):
                listing["_identified_brand"] = vision_result["brand"]
            if vision_result.get("model"):
                listing["_identified_model"] = vision_result["model"]
            if vision_result.get("is_bundle"):
                listing["is_bundle"] = True
                listing["bundle_components"] = vision_result.get("bundle_items", [])
            
            print(f"   ✅ Identified: {vision_result.get('product_type', 'Unknown')}")
            if vision_result.get("brand"):
                print(f"      Brand: {vision_result['brand']}")
            if vision_result.get("is_bundle"):
                print(f"      Bundle: {len(vision_result.get('bundle_items', []))} items")
        else:
            print(f"   ⚠️ Vision failed: {vision_result.get('notes', 'Unknown error')}")
    
    print(f"\n✅ Vision analysis complete ({len(to_analyze)} images)")
    
    return listings


# ==============================================================================
# COST TRACKING & BUDGET MANAGEMENT
# ==============================================================================

def reset_run_cost():
    """Reset run cost counter."""
    global RUN_COST_USD
    RUN_COST_USD = 0.0


def add_cost(amount: float):
    """Add cost to run total."""
    global RUN_COST_USD
    RUN_COST_USD += amount


def get_run_cost_summary() -> Dict[str, Any]:
    """Get summary of current run cost.
    
    Returns:
        Dict with keys:
            - total_usd: float - Total cost in USD for current run
            - date: str - Current date in YYYY-MM-DD format
    """
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    result = {
        "total_usd": RUN_COST_USD,
        "date": today
    }
    
    # PART C: Type assertion for TEST mode - ensures return type is always dict
    try:
        from runtime_mode import get_mode_config
        from config import load_config
        cfg = load_config()
        mode_config = get_mode_config(cfg.runtime.mode)
        
        if mode_config.mode.value == "test":
            assert isinstance(result, dict), f"get_run_cost_summary() must return dict, got {type(result)}"
            assert "total_usd" in result, "get_run_cost_summary() dict must have 'total_usd' key"
            assert "date" in result, "get_run_cost_summary() dict must have 'date' key"
    except ImportError:
        pass  # runtime_mode not available, skip assertion
    
    return result


def get_day_cost_summary() -> float:
    """Get today's total cost as float."""
    try:
        if os.path.exists(DAY_COST_FILE):
            with open(DAY_COST_FILE, "r") as f:
                content = f.read().strip()
                if "," in content:
                    date_str, cost_str = content.split(",", 1)
                    today = datetime.datetime.now().strftime("%Y-%m-%d")
                    if date_str == today:
                        return float(cost_str)
                    return 0.0  # Different day, reset
                return float(content)  # Legacy format
    except:
        pass
    return 0.0


def save_day_cost() -> float:
    """
    v7.3.5 FIX: Save current run cost to daily total file.
    
    This was MISSING before - day costs were never persisted!
    Now stores format: "YYYY-MM-DD,total_cost"
    
    Returns: New daily total
    """
    global RUN_COST_USD
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        existing = 0.0
        
        # Read existing costs for today
        if os.path.exists(DAY_COST_FILE):
            with open(DAY_COST_FILE, "r") as f:
                content = f.read().strip()
                if "," in content:
                    date_str, cost_str = content.split(",", 1)
                    if date_str == today:
                        existing = float(cost_str)
                    # else: different day, start fresh
        
        # Add this run's cost
        new_total = existing + RUN_COST_USD
        
        # Save with date prefix
        with open(DAY_COST_FILE, "w") as f:
            f.write(f"{today},{new_total:.4f}")
        
        print(f"💾 Saved day cost: ${new_total:.4f} (this run: ${RUN_COST_USD:.4f})")
        return new_total
    except Exception as e:
        print(f"⚠️ Could not save day cost: {e}")
        return 0.0


def is_budget_exceeded() -> bool:
    """Check if daily budget is exceeded."""
    day_cost = get_day_cost_summary()
    return day_cost >= DAILY_COST_LIMIT


def apply_config(config):
    """Apply configuration from config dict or config object."""
    global RICARDO_FEE_PERCENT, SHIPPING_COST_CHF, MIN_PROFIT_THRESHOLD
    global BUNDLE_ENABLED, BUNDLE_DISCOUNT_PERCENT, BUNDLE_MIN_COMPONENT_VALUE
    global CACHE_ENABLED, USE_VISION, VISION_RATE, DEFAULT_CAR_MODEL
    global WEB_SEARCH_ENABLED  # v7.3.2: Toggle expensive web search
    
    # Handle both dict and object config
    def get_val(key, default=None):
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)
    
    # Try to get values from general section first, then direct
    def get_nested(section, key, default=None):
        if isinstance(config, dict):
            sec = config.get(section, {})
            if isinstance(sec, dict):
                return sec.get(key, default)
            return getattr(sec, key, default)
        sec = getattr(config, section, None)
        if sec:
            return getattr(sec, key, default)
        return getattr(config, key, default)
    
    val = get_nested("general", "ricardo_fee_percent", None)
    if val is not None:
        RICARDO_FEE_PERCENT = val
    val = get_nested("general", "shipping_cost_chf", None)
    if val is not None:
        SHIPPING_COST_CHF = val
    val = get_nested("general", "min_profit_threshold", None)
    if val is not None:
        MIN_PROFIT_THRESHOLD = val
    val = get_nested("bundle", "enabled", None)
    if val is not None:
        BUNDLE_ENABLED = val
    val = get_nested("bundle", "discount_percent", None)
    if val is not None:
        BUNDLE_DISCOUNT_PERCENT = val
    val = get_nested("bundle", "min_component_value", None)
    if val is not None:
        BUNDLE_MIN_COMPONENT_VALUE = val
    val = get_nested("cache", "enabled", None)
    if val is not None:
        CACHE_ENABLED = val
    val = get_nested("ai", "use_vision", None)
    if val is not None:
        USE_VISION = val
    val = get_nested("ai", "vision_rate", None)
    if val is not None:
        VISION_RATE = val
    val = get_nested("general", "car_model", None)
    if val is not None:
        DEFAULT_CAR_MODEL = val
    
    # v7.3.2: Read web search enabled setting from ai.web_search.enabled
    if isinstance(config, dict):
        ai_section = config.get("ai", {})
        if isinstance(ai_section, dict):
            ws_section = ai_section.get("web_search", {})
            if isinstance(ws_section, dict):
                val = ws_section.get("enabled", None)
                if val is not None:
                    WEB_SEARCH_ENABLED = val
                    status = "ENABLED ✅" if val else "DISABLED ❌ (cost saving mode)"
                    print(f"  Web Search:       {status}")


def apply_ai_budget_from_cfg(config):
    """Apply AI budget settings from config object or dict."""
    global DAILY_COST_LIMIT, DAILY_VISION_LIMIT, DAILY_WEB_SEARCH_LIMIT
    
    # Handle both dict and object config
    def get_val(key, default=None):
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)
    
    val = get_val("daily_cost_limit", None)
    if val is not None:
        DAILY_COST_LIMIT = val
    val = get_val("daily_vision_limit", None)
    if val is not None:
        DAILY_VISION_LIMIT = val
    val = get_val("daily_web_search_limit", None)
    if val is not None:
        DAILY_WEB_SEARCH_LIMIT = val


def clear_all_caches():
    """Clear all cache files."""
    global _variant_cache, _component_cache, _cluster_cache, _web_price_cache, _category_threshold_cache
    
    _variant_cache = {}
    _component_cache = {}
    _cluster_cache = {}
    _web_price_cache = {}
    _category_threshold_cache = {}
    
    for cache_file in [VARIANT_CACHE_FILE, COMPONENT_CACHE_FILE, CLUSTER_CACHE_FILE, 
                       WEB_PRICE_CACHE_FILE, CATEGORY_THRESHOLD_CACHE_FILE]:
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"🗑️ Cleared: {cache_file}")


# ==============================================================================
# HELPER FOR MAIN.PY COMPATIBILITY
# ==============================================================================

def cluster_variants_from_titles(
    titles: List[str],
    base_product: str,
    query_analysis: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Cluster variant titles into groups.
    
    Returns:
        {
            "variants": {"variant_key": ["title1", "title2", ...]},
            "base_product": str,
        }
    """
    if not titles:
        return {"variants": {}, "base_product": base_product}
    
    _load_caches()
    
    # Check cache
    cache_key = f"{base_product}_{len(titles)}"
    if cache_key in _cluster_cache:
        cached = _cluster_cache[cache_key]
        if cached.get("expires_at", "") > datetime.datetime.now().isoformat():
            print(f"   💾 Cluster cache hit: {len(cached.get('variants', {}))} variants")
            return cached
    
    # Simple clustering: group by exact title match
    variants = {}
    for title in titles:
        # Use title as variant key (simplified)
        variant_key = title.strip()
        if variant_key not in variants:
            variants[variant_key] = []
        variants[variant_key].append(title)
    
    result = {
        "variants": variants,
        "base_product": base_product,
    }
    
    # Cache for 7 days
    now = datetime.datetime.now()
    expires = now + datetime.timedelta(days=CLUSTER_CACHE_DAYS)
    _cluster_cache[cache_key] = {
        **result,
        "cached_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }
    _save_cluster_cache()
    
    print(f"   🔍 Clustered {len(titles)} titles into {len(variants)} variants")
    return result


def get_variant_for_title(title: str, cluster_result: Dict[str, Any], base_product: str) -> str:
    """Get variant key for a title from cluster result."""
    if not title or not cluster_result:
        return base_product
    
    variants = cluster_result.get("variants", {})
    
    # Find which variant this title belongs to
    for variant_key, titles in variants.items():
        if title in titles:
            return variant_key
    # Fallback: use title as variant key
    return title.strip() or base_product


def to_float(val: Any) -> Optional[float]:
    """Safely convert value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_lowest_variant_resale(base_product: str) -> Optional[float]:
    """Get lowest resale price for any variant of a product."""
    _load_caches()
    prices = [
        info.get("resale_price") 
        for vk, info in _variant_cache.items() 
        if vk and (vk.startswith(base_product + "|") or vk == base_product) 
        and info.get("resale_price", 0) > 0
    ]
    return round(min(prices), 2) if prices else None


def init_ai_filter(cfg):
    """
    Initialize AI Filter with config and validate Claude model configuration.
    MUST be called before any AI operations.
    
    Args:
        cfg: Configuration object with ai.claude_model_fast and ai.claude_model_web
    
    Raises:
        RuntimeError: If Claude model configuration is invalid
    """
    global _config
    _config = cfg
    
    # Validate Claude model configuration if Claude is the provider
    if cfg.ai.provider == "claude":
        if not cfg.ai.claude_model_fast:
            raise RuntimeError("❌ CONFIG ERROR: ai.claude_model_fast is empty")
        
        if cfg.ai.claude_model_fast != "claude-3-5-haiku-20241022":
            raise RuntimeError(
                f"❌ CONFIG ERROR: Invalid Claude fast model '{cfg.ai.claude_model_fast}'\n"
                f"   Expected: 'claude-3-5-haiku-20241022' (Haiku 3.5)\n"
                f"   This project uses Haiku 3.5 only. Update config.yaml."
            )
        
        if not cfg.ai.claude_model_web:
            raise RuntimeError("❌ CONFIG ERROR: ai.claude_model_web is empty")
        
        print(f"✅ AI Filter configured: {cfg.ai.claude_model_fast} (fast), {cfg.ai.claude_model_web} (web)")