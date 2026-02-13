"""
AI Filter & Evaluation - v8.0 (Stabilized Edition)
===================================================
v8.0 Changes:
- Price sanity validation gates (resale <= new price)
- Minimum profit threshold enforced (20 CHF)
- Cross-run market aggregation via identity_key
- Soft market pricing with DB persistence
- Improved observability and logging

AI Configuration:
- Claude Haiku: Fast extraction
- Claude Sonnet: Web search for new prices
- OpenAI: Automatic fallback

Pricing Priority Chain:
1. learned_market (from products.resale_estimate)
2. market_auction (calculated from bid data)
3. web_single/web_median (from web search)
4. current_bid_floor (if bids_count > 0)
5. ai_estimate (discounted 50%)
6. query_baseline (category-based fallback)

Validation Gates:
- Price sanity: resale <= new price
- Profit threshold: minimum 20 CHF
- Sample requirements: >= 2 for market pricing

Bundle Support: DISABLED (bundles_disabled=True)
- Code preserved for future Phase 3 implementation
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
from utils_text import extract_weight_kg

# ==============================================================================
# v8.1: MODULAR IMPORTS (extracted modules for cleaner architecture)
# ==============================================================================
# Re-export from new modules for backwards compatibility
from evaluation.strategy import (
    determine_strategy as _determine_strategy,
    calculate_deal_score as _calculate_deal_score,
    set_min_profit_threshold,
)
from pricing.market_pricing import (
    calculate_market_resale_from_listings as _calculate_market_resale_from_listings,
    calculate_all_market_resale_prices as _calculate_all_market_resale_prices,
    calculate_soft_market_price as _calculate_soft_market_price,
    apply_soft_market_cap as _apply_soft_market_cap,
    predict_final_auction_price as _predict_final_auction_price,
)
from bundles.bundle_detector import (
    looks_like_bundle as _looks_like_bundle,
    detect_bundle_with_ai as _detect_bundle_with_ai,
    price_bundle_components_v2 as _price_bundle_components_v2,
    calculate_bundle_new_price as _calculate_bundle_new_price,
    calculate_bundle_resale as _calculate_bundle_resale,
    get_weight_type,
    set_bundle_config,
    BUNDLE_KEYWORDS,
    WEIGHT_PLATE_KEYWORDS,
    WEIGHT_PRICING,
)

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

# Import cache helper functions
from ai_filter_cache_helpers import (
    get_cached_web_price,
    set_cached_web_price,
    get_cached_variant_info,
    set_cached_variant_info,
    load_caches as load_cache_helpers
)


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

# PHASE 6: VALIDATION GATE - Minimum Profit Threshold
# Ensures only deals with sufficient profit are recommended
# Enforced in determine_strategy() - deals below this threshold are marked as "skip"
MIN_PROFIT_THRESHOLD = 20.0  # CHF

BUNDLE_ENABLED = False  # Set via config.yaml
BUNDLE_DISCOUNT_PERCENT = 0.10
BUNDLE_MIN_COMPONENT_VALUE = 10.0
MAX_COMPONENT_PRICE = 300.0  # Max realistic price per component (CHF)
BUNDLE_USE_VISION = False  # Set via config.yaml
BUNDLE_ALWAYS_SCRAPE_DETAIL = True  # Set via config.yaml

# v9.0: Fitness weight pricing constants
WEIGHT_PLATE_KEYWORDS = [
    "hantelscheibe", "gewicht", "plate", "scheibe", "bumper",
    "weight", "kg", "hantel", "langhantel", "kurzhantel",
]

WEIGHT_PRICING = {
    "bumper": {"new_price_per_kg": 6.0, "resale_rate": 0.70},
    "gummi": {"new_price_per_kg": 5.0, "resale_rate": 0.65},
    "guss": {"new_price_per_kg": 3.0, "resale_rate": 0.60},
    "calibrated": {"new_price_per_kg": 12.0, "resale_rate": 0.75},
    "standard": {"new_price_per_kg": 3.5, "resale_rate": 0.60},
}

def get_weight_type(name: str) -> str:
    """Detect weight plate type from name for pricing."""
    name_lower = name.lower() if name else ""
    if "bumper" in name_lower:
        return "bumper"
    if "gummi" in name_lower or "rubber" in name_lower:
        return "gummi"
    if "guss" in name_lower or "cast" in name_lower or "eisen" in name_lower:
        return "guss"
    if "calibrated" in name_lower or "kalibriert" in name_lower or "competition" in name_lower:
        return "calibrated"
    return "standard"

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
        
        # Track cost based on call type
        if use_web_search:
            add_cost(COST_CLAUDE_WEB_SEARCH)
        elif image_url:
            add_cost(COST_VISION)
        else:
            add_cost(COST_CLAUDE_HAIKU)
        
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
def extract_json_array_from_text(text: str):
    """Robust JSON array extraction from LLM response text.
    
    Handles:
    - Markdown fences (```json ... ```)
    - Leading/trailing explanations
    - Single object instead of array
    - JSON embedded in text
    
    Returns:
        List of dicts if successful, None if parsing fails
    """
    import json
    import re
    
    # 1. Remove markdown fences
    text = re.sub(r"```(?:json)?", "", text)
    text = text.replace("```", "").strip()
    
    # 2. Try direct parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass
    
    # 3. Extract first JSON array via regex
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    
    # 4. Extract first JSON object and wrap into array
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass
    
    return None


def search_web_batch_for_new_prices(
    variant_keys: List[str],
    category: str = "unknown",
    query_analysis: Optional[Dict] = None,
    market_prices_count: int = 0,
    listings_with_bids: int = 0
) -> Dict[str, Dict[str, Any]]:
    """
    v7.3.4: SINGLE WEB SEARCH STRATEGY - 83% cost reduction!
    
    TASK 2: WEBSEARCH GATING (Hybrid Strategy)
    - Only runs if market signal exists (market_prices > 0 OR bids ≥ 3)
    - Prevents expensive calls in early runs with no validation baseline
    - Falls back to query_baseline (free, deterministic)
    
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
    
    # TASK 2: WEBSEARCH GATING - Hybrid Strategy (Option C)
    # Only run websearch if we have market signal to validate against
    if market_prices_count == 0 and listings_with_bids < 3:
        print(f"\n⏭️ SKIPPING WEBSEARCH: No market signal for validation")
        print(f"   Market prices: {market_prices_count}")
        print(f"   Listings with bids: {listings_with_bids}")
        print(f"   → Using query_baseline (free, deterministic)")
        print(f"   💰 Cost saved: ~${len(variant_keys) * 0.04:.2f}")
        print(f"   ✅ Quality preserved: query_baseline provides same value in early runs")
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
            
            # Parse JSON array response with robust extraction
            parsed = extract_json_array_from_text(raw)
            
            if parsed is None:
                print(f"   WEBSEARCH PARSE ERROR")
                print(f"   Raw preview: {raw[:500]}")
                print(f"   → Falling back to query_baseline (no AI fallback)")
                # CRITICAL: Do NOT trigger AI fallback - it will also fail and waste money
                # Empty results will cause caller to use query_baseline (free, deterministic)
                continue
            
            print(f"   WEBSEARCH PARSE SUCCESS: {len(parsed)} items")
            
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
# HELPER FUNCTIONS FOR QUERY ANALYSIS
# ==============================================================================

def is_commodity_variant(variant_key: str, category: str, websearch_query: str = None) -> bool:
    """Check if variant is a commodity with stable prices (skip websearch)."""
    # Stub implementation - commodities are rare, default to False
    return False


def is_weight_plate(variant_key: str) -> bool:
    """Check if variant is a weight plate (fitness equipment)."""
    if not variant_key:
        return False
    vk_lower = variant_key.lower()
    return any(kw in vk_lower for kw in ["hantel", "gewicht", "plate", "scheibe", "kg"])


def validate_weight_price(variant_key: str, price: float, is_resale: bool = False) -> Tuple[float, str]:
    """Validate and adjust weight plate prices based on kg."""
    # Stub implementation - return price as-is
    return (price, "no_adjustment")


def _get_new_price_estimate(query_analysis: Optional[Dict] = None) -> float:
    """Gets new price estimate from query analysis."""
    if query_analysis:
        return query_analysis.get("new_price_estimate", 275.0)
    return 275.0


def _get_min_realistic_price(query_analysis: Optional[Dict] = None) -> float:
    """Gets minimum realistic price from query analysis."""
    if query_analysis:
        return query_analysis.get("min_realistic_price", 10.0)
    return 10.0


def _get_auction_multiplier(query_analysis: Optional[Dict] = None) -> float:
    """Gets auction typical multiplier from query analysis."""
    if query_analysis:
        return query_analysis.get("auction_typical_multiplier", 5.0)
    return 5.0


def _get_resale_rate(query_analysis: Optional[Dict] = None) -> float:
    """Gets resale rate from query analysis."""
    if query_analysis:
        return query_analysis.get("resale_rate", 0.40)
    return 0.40


def _get_category(query_analysis: Optional[Dict] = None) -> str:
    """Gets category from query analysis."""
    if query_analysis:
        return query_analysis.get("category", "unknown")
    return "unknown"


def fetch_variant_info_batch(
    variant_keys: List[str],
    car_model: str = DEFAULT_CAR_MODEL,
    market_prices: Optional[Dict[str, Dict[str, Any]]] = None,
    query_analysis: Optional[Dict] = None,
    live_bid_count: int = 0
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch variant info (new price, resale, transport) for multiple variants.
    
    TASK 3: AI FALLBACK REMOVED
    Flow: market_price → live_bid_floor → websearch (if gated) → query_baseline (FINAL)
    
    Args:
        live_bid_count: Count of listings with bids_count > 0 (market signal for websearch validation)
    """
    if not variant_keys:
        return {}
    
    market_prices = market_prices or {}
    resale_rate = _get_resale_rate(query_analysis)
    category = _get_category(query_analysis)
    
    results = {}
    
    # Phase 1: Check market prices first
    for vk in variant_keys:
        if vk in market_prices:
            results[vk] = market_prices[vk].copy()
    
    # Phase 2: Web search for variants still missing prices
    need_new_price = [vk for vk in variant_keys if vk not in results or results[vk].get("new_price") is None]
    
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

            # TASK 2: Pass market signal metrics for gating
            market_prices_count = len([v for v in variant_keys if v in market_prices])
            # FIXED: Use live_bid_count from main.py (actual listings with bids_count > 0)
            # This promotes live bids to valid market signals for websearch validation
            listings_with_bids = live_bid_count
            
            # v7.3.3: Pass query_analysis for better search term cleaning
            web_results = search_web_batch_for_new_prices(
                websearch_variants, 
                category, 
                query_analysis,
                market_prices_count=market_prices_count,
                listings_with_bids=listings_with_bids
            )
        else:
            web_results = {}
        
        # Merge web results
        for vk, web_result in web_results.items():
            # FIX 2: Websearch success = numeric price returned (not None)
            if web_result and web_result.get("new_price") is not None and web_result.get("new_price") > 0:
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
                # No web result, will use query_baseline
                if vk not in results:
                    results[vk] = {
                        "new_price": None,
                        "transport_car": True,
                        "resale_price": None,
                        "market_based": False,
                        "market_sample_size": 0,
                    }
    
    return results


def calculate_market_resale_from_listings(
    identity_key: str,
    listings: List[Dict[str, Any]],
    reference_price: Optional[float] = None,
    unrealistic_floor: float = 10.0,
    context=None,
    ua: str = None,
    variant_new_price: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    PHASE 4.2: Calculate market resale price from listings with same identity_key.
    
    Aggregates across variants (e.g., iPhone 12 mini 128GB + 256GB together).
    Uses live bid data from current Ricardo auctions.
    """
    if not identity_key:
        return None
    
    # Filter listings by identity_key
    matching = [l for l in listings if l.get("_identity_key") == identity_key]
    
    print(f"         🔍 Filtering {len(listings)} listings for identity_key='{identity_key}'")
    print(f"         Matching listings: {len(matching)}")
    
    if not matching:
        print(f"         ❌ No matching listings found")
        return None
    
    # Collect bid samples with smart filtering
    # Strategy: Accept active auctions (bids_count > 0) with low floor (5 CHF)
    #           Accept starting bids (bids_count = 0) with high floor (unrealistic_floor)
    samples = []
    rejected_count = 0
    ACTIVE_AUCTION_MIN_PRICE = 5.0  # Low floor for auctions with active bids
    
    for listing in matching:
        bid = listing.get("current_bid")
        bids_count = listing.get("bids_count", 0)
        
        if not bid:
            rejected_count += 1
            print(f"         ❌ Rejected: bid={bid}, bids_count={bids_count}, reason=no_bid")
            continue
        
        # Accept if: Active auction (bids_count > 0) with reasonable price
        if bids_count > 0 and bid >= ACTIVE_AUCTION_MIN_PRICE:
            samples.append(bid)
            print(f"         ✅ Sample: bid={bid} CHF, bids_count={bids_count} (active auction)")
        # Accept if: Starting bid (bids_count = 0) but high enough to be realistic
        elif bids_count == 0 and bid >= unrealistic_floor:
            samples.append(bid)
            print(f"         ✅ Sample: bid={bid} CHF, bids_count={bids_count} (high starting bid)")
        else:
            rejected_count += 1
            if bids_count > 0:
                reason = f"below_active_floor (bid={bid} < {ACTIVE_AUCTION_MIN_PRICE})"
            else:
                reason = f"below_starting_floor (bid={bid} < {unrealistic_floor})"
            print(f"         ❌ Rejected: bid={bid}, bids_count={bids_count}, reason={reason}")
    
    print(f"         Valid samples: {len(samples)}, Rejected: {rejected_count}")
    
    if len(samples) < 2:
        print(f"         ❌ Insufficient samples ({len(samples)} < 2 required)")
        return None
    
    # Calculate median
    median_price = statistics.median(samples)
    
    return {
        "resale_price": round(median_price, 2),
        "source": "market_auction",
        "sample_size": len(samples),
        "market_based": True,
    }


def calculate_all_market_resale_prices(
    listings: List[Dict[str, Any]],
    variant_new_prices: Optional[Dict[str, float]] = None,
    unrealistic_floor: float = 10.0,
    typical_multiplier: float = 5.0,
    context=None,
    ua: str = None,
    query_analysis: Optional[Dict] = None,
    conn=None,
    run_id: str = None
) -> Dict[str, Dict[str, Any]]:
    """
    PHASE 4.2: Aggregate market prices by canonical_identity_key.
    
    Uses cross-run DB data for each identity_key to enable market price aggregation.
    This allows listings with different storage/color to aggregate together.
    Example: iPhone 12 mini 128GB + iPhone 12 mini 256GB → same market price pool
    """
    # PHASE 4.2: Group by canonical_identity_key instead of variant_key
    identity_keys = set(l.get("_identity_key") for l in listings if l.get("_identity_key"))
    variant_new_prices = variant_new_prices or {}
    reference_price = _get_new_price_estimate(query_analysis)
    
    if query_analysis:
        unrealistic_floor = _get_min_realistic_price(query_analysis)
    
    # DEBUG: Market price aggregation diagnostics
    print(f"\n🔍 MARKET PRICE AGGREGATION DEBUG:")
    print(f"   Total listings: {len(listings)}")
    print(f"   Unique identity_keys: {len(identity_keys)}")
    print(f"   Unrealistic floor: {unrealistic_floor} CHF")
    print(f"   Identity keys: {list(identity_keys)[:5]}...") if len(identity_keys) > 5 else print(f"   Identity keys: {list(identity_keys)}")
    
    results = {}
    for identity_key in identity_keys:
        print(f"\n   🔑 Processing identity_key: '{identity_key}'")
        
        # Use first variant_key for new price lookup (backwards compatibility)
        matching_listings = [l for l in listings if l.get("_identity_key") == identity_key]
        print(f"      Current run listings: {len(matching_listings)}")
        
        first_variant_key = matching_listings[0].get("variant_key") if matching_listings else None
        variant_new = variant_new_prices.get(first_variant_key) if matching_listings else None
        
        # CROSS-RUN FIX: Fetch persisted DB listings for this identity_key
        # This enables market price aggregation across runs (same as soft market)
        if conn and run_id:
            from db_pg_v2 import get_listings_by_search_identity
            db_listings = get_listings_by_search_identity(conn, run_id, identity_key)
            print(f"      DB listings fetched: {len(db_listings)}")
            
            # Combine current run + persisted listings
            all_listings_for_identity = matching_listings + db_listings
            
            # 🔍 OBSERVABILITY: Market aggregation sample validation
            unique_source_ids = len(set(
                l.get("listing_id") for l in all_listings_for_identity
                if l.get("listing_id") is not None
            ))
            
            print(f"      📊 MARKET SAMPLE STATS:")
            print(f"         Raw samples: {len(all_listings_for_identity)}")
            print(f"         Unique listings: {unique_source_ids}")
        else:
            # Fallback: use only current run listings
            all_listings_for_identity = matching_listings
            print(f"      ⚠️ No DB connection - using only current run listings")
        
        # Calculate market data using canonical identity (aggregates across variants)
        market_data = calculate_market_resale_from_listings(identity_key, all_listings_for_identity, reference_price, unrealistic_floor, context, ua, variant_new)
        if market_data:
            results[identity_key] = market_data
            sample_count = market_data.get('sample_size', 0)
            print(f"      ✅ Market price calculated: {market_data['resale_price']} CHF ({sample_count} samples)")
        else:
            print(f"      ❌ No market price calculated (insufficient samples)")
    
    return results


def _fetch_variant_info_from_ai_batch(variant_keys: List[str], car_model: str = DEFAULT_CAR_MODEL, market_prices: Optional[Dict[str, Dict[str, Any]]] = None, query_analysis: Optional[Dict] = None) -> Dict[str, Dict[str, Any]]:
    """AI-based variant info estimation (fallback when web search fails)."""
    # ... (rest of the code remains the same)
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


def price_bundle_components_v2(
    components: List["BundleComponent"],
    category: Optional[str] = None,
    query_analysis: Optional[Dict] = None,
    conn=None,
    run_id: str = None,
) -> List["BundleComponent"]:
    """
    v8.0: Price bundle components using market data + weight-based fallbacks.
    
    Pricing Priority (per component):
    1. market_auction: Median of concurrent auctions with same identity_key
    2. web_single: Pre-fetched new price × resale_rate
    3. weight_based: For fitness weights (CHF/kg × weight)
    4. ai_estimate: Fallback estimation
    
    Args:
        components: List of BundleComponent objects
        category: Product category (e.g., "fitness")
        query_analysis: Query analysis for resale rates
        conn: Database connection for market data lookup
        run_id: Current run ID for market data lookup
    
    Returns:
        List of BundleComponent with pricing populated
    """
    from models.bundle_component import BundleComponent
    
    resale_rate = _get_resale_rate(query_analysis)
    is_fitness = category == "fitness" if category else False
    
    priced = []
    
    for comp in components:
        # Skip invalid components
        if not comp.product_type or comp.quantity <= 0:
            print(f"      Skipping invalid component: {comp.display_name}")
            continue
        
        # === PRIORITY 1: Market data lookup ===
        market_price = None
        if conn and run_id and comp.identity_key:
            market_price = _get_market_price_for_component(
                conn, run_id, comp.identity_key
            )
        
        if market_price:
            comp.resale_price = market_price["resale_price"]
            comp.price_source = "market_auction"
            print(f"      {comp.display_name}: {comp.resale_price:.2f} CHF (market, n={market_price.get('sample_size', 0)})")
        
        # === PRIORITY 2: Weight-based pricing for fitness ===
        elif is_fitness and comp.product_type in ["hantelscheibe", "kurzhantel", "kettlebell"]:
            weight_kg = comp.specs.get("weight_kg")
            if weight_kg and weight_kg > 0:
                material = comp.specs.get("material", "standard")
                new_price = _calculate_weight_price(weight_kg, material)
                comp.new_price = new_price
                comp.resale_price = new_price * 0.60  # Fitness resale rate
                comp.price_source = "weight_based"
                print(f"      {comp.display_name}: {comp.resale_price:.2f} CHF ({weight_kg}kg × rate)")
            else:
                # Weight plate without weight = skip
                print(f"      {comp.display_name}: No weight specified, skipping")
                continue
        
        # === PRIORITY 3: AI estimation fallback ===
        else:
            est_new = _estimate_component_price(comp.display_name, category or "general", query_analysis)
            if est_new and est_new > 0:
                comp.new_price = est_new
                component_resale_rate = _get_component_resale_rate(comp.display_name, category or "general", resale_rate)
                comp.resale_price = est_new * component_resale_rate
                comp.price_source = "ai_estimate"
                print(f"      {comp.display_name}: {comp.resale_price:.2f} CHF (AI estimate)")
            else:
                print(f"      {comp.display_name}: Price unavailable, skipping")
                continue
        
        # Calculate unit_value (resale × quantity)
        comp.calculate_unit_value()
        
        # Validate: Skip if unit_value is unreasonable
        if comp.unit_value and comp.unit_value > MAX_COMPONENT_PRICE * comp.quantity:
            print(f"      {comp.display_name}: Value {comp.unit_value:.2f} exceeds max, skipping")
            continue
        
        priced.append(comp)
    
    return priced


def _get_market_price_for_component(
    conn, 
    run_id: str, 
    identity_key: str
) -> Optional[Dict[str, Any]]:
    """
    Get market price for a component by identity_key.
    
    Queries DB for listings with same identity_key and calculates median.
    """
    try:
        from db_pg_v2 import get_listings_by_search_identity
        
        db_listings = get_listings_by_search_identity(conn, run_id, identity_key)
        
        if len(db_listings) < 2:
            return None
        
        # Collect valid samples (active auctions with bids)
        samples = []
        for listing in db_listings:
            bid = listing.get("current_bid")
            bids_count = listing.get("bids_count", 0)
            
            if bid and bids_count > 0 and bid >= 5.0:
                samples.append(bid)
        
        if len(samples) < 2:
            return None
        
        median_price = statistics.median(samples)
        
        return {
            "resale_price": round(median_price, 2),
            "sample_size": len(samples),
            "source": "market_auction",
        }
    except Exception as e:
        print(f"      Market lookup failed for {identity_key}: {e}")
        return None


def _calculate_weight_price(weight_kg: float, material: str) -> float:
    """
    Calculate new price for weight plates based on weight and material.
    
    Pricing (CHF per kg for NEW):
    - Bumper plates: 5-7 CHF/kg
    - Cast iron: 2-3 CHF/kg
    - Calibrated: 10-15 CHF/kg
    - Standard: 3-4 CHF/kg
    """
    material_lower = material.lower() if material else "standard"
    
    # CHF per kg pricing for NEW weights
    WEIGHT_PRICING = {
        "bumper": 6.0,
        "gummi": 6.0,
        "rubber": 6.0,
        "gusseisen": 2.5,
        "cast iron": 2.5,
        "eisen": 2.5,
        "calibrated": 12.0,
        "competition": 12.0,
        "wettkampf": 12.0,
        "urethane": 8.0,
        "chrome": 4.0,
        "chrom": 4.0,
        "vinyl": 2.0,
        "standard": 3.5,
    }
    
    price_per_kg = WEIGHT_PRICING.get(material_lower, 3.5)
    
    return round(weight_kg * price_per_kg, 2)


def predict_final_auction_price(
    current_price: float,
    bids_count: int,
    hours_remaining: float,
    median_price: Optional[float] = None,
    new_price: Optional[float] = None,
    typical_multiplier: float = 5.0
) -> Dict[str, Any]:
    """Predict final auction price based on current bid, time, and activity."""
    if current_price <= 0:
        return {"predicted_final_price": 0.0, "confidence": 0.0}
    
    # Base multiplier based on time remaining
    if hours_remaining < 1:
        time_multiplier = 1.05
    elif hours_remaining < 24:
        time_multiplier = 1.15
    elif hours_remaining < 72:
        time_multiplier = 1.25
    else:
        time_multiplier = 1.35
    
    # Bid activity multiplier
    if bids_count >= 50:
        bid_multiplier = 1.20
    elif bids_count >= 20:
        bid_multiplier = 1.15
    elif bids_count >= 10:
        bid_multiplier = 1.10
    elif bids_count >= 5:
        bid_multiplier = 1.05
    else:
        bid_multiplier = 1.0
    
    # Calculate predicted price
    predicted = current_price * time_multiplier * bid_multiplier
    
    # Cap at median or new price if available
    if median_price and predicted > median_price * 1.2:
        predicted = median_price * 1.2
    elif new_price and predicted > new_price * 0.7:
        predicted = new_price * 0.7
    
    # Confidence based on data availability
    confidence = 0.5
    if median_price:
        confidence = 0.75
    if bids_count >= 10:
        confidence += 0.1
    
    return {
        "predicted_final_price": round(predicted, 2),
        "confidence": min(0.95, confidence)
    }


def calculate_soft_market_price(
    search_identity: str,
    all_listings_for_variant: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Calculate soft market price from current bids on similar listings."""
    if not search_identity or not all_listings_for_variant:
        return None
    
    # DEDUPLICATION: Remove duplicate listings by source_id (same listing from DB + current run)
    seen_source_ids = set()
    unique_listings = []
    for listing in all_listings_for_variant:
        source_id = listing.get("source_id") or listing.get("listing_id")
        if source_id and source_id in seen_source_ids:
            continue
        if source_id:
            seen_source_ids.add(source_id)
        unique_listings.append(listing)
    
    if len(unique_listings) < len(all_listings_for_variant):
        print(f"   SOFT MARKET: Deduplicated {len(all_listings_for_variant)} → {len(unique_listings)} unique listings")
    
    # Filter valid samples with bids
    valid_samples = []
    print(f"   SOFT MARKET DEBUG: Processing {len(unique_listings)} listings for identity='{search_identity}'")
    for idx, listing in enumerate(unique_listings):
        bid = listing.get("current_bid") or listing.get("current_price_ricardo")
        bids_count = listing.get("bids_count", 0)
        hours_remaining = listing.get("hours_remaining", 999)
        
        print(f"      [{idx}] bid={bid}, bids_count={bids_count}, hours_remaining={hours_remaining}")
        
        if not bid or bid <= 0 or bids_count == 0:
            print(f"      [{idx}] REJECTED: bid={bid}, bids_count={bids_count}")
            continue
        
        # Time adjustment factor
        if hours_remaining < 1:
            time_factor = 1.05
        elif hours_remaining < 24:
            time_factor = 1.10
        elif hours_remaining < 72:
            time_factor = 1.15
        else:
            time_factor = 1.20
        
        adjusted_bid = bid * time_factor
        valid_samples.append(adjusted_bid)
        print(f"      [{idx}] ACCEPTED: adjusted_bid={adjusted_bid:.2f}")
    
    print(f"   SOFT MARKET DEBUG: valid_samples count={len(valid_samples)}")
    
    # Require at least 2 samples
    if len(valid_samples) < 2:
        return None
    
    # Calculate median
    valid_samples.sort()
    median_idx = len(valid_samples) // 2
    if len(valid_samples) % 2 == 0:
        soft_price = (valid_samples[median_idx-1] + valid_samples[median_idx]) / 2
    else:
        soft_price = valid_samples[median_idx]
    
    # Confidence based on sample size
    if len(valid_samples) >= 5:
        confidence = 0.70
    elif len(valid_samples) >= 3:
        confidence = 0.60
    else:
        confidence = 0.50
    
    return {
        "soft_market_price": round(soft_price, 2),
        "confidence": confidence,
        "sample_count": len(valid_samples),
        "samples": valid_samples
    }


def apply_soft_market_cap(
    result: Dict[str, Any],
    soft_market_data: Dict[str, Any],
    search_identity: str
) -> Dict[str, Any]:
    """Apply soft market cap to resale price estimate (ceiling only)."""
    if not soft_market_data:
        return result
    
    soft_price = soft_market_data["soft_market_price"]
    soft_confidence = soft_market_data["confidence"]
    sample_count = soft_market_data["sample_count"]
    
    original_resale = result.get("resale_price_est", 0)
    if not original_resale or original_resale <= 0:
        return result
    
    # Safety factor: allow 10% above soft price
    safety_factor = 1.10
    soft_cap = soft_price * safety_factor
    
    # Only apply if current estimate exceeds soft cap
    if original_resale <= soft_cap:
        return result
    
    # Calculate cap impact
    cap_reduction_pct = (original_resale - soft_cap) / original_resale * 100
    
    # Store original before capping
    result["original_resale_before_cap"] = original_resale
    
    # Apply cap
    result["resale_price_est"] = soft_cap
    
    # Add soft market metadata
    result["soft_market_cap_applied"] = True
    result["soft_market_price"] = soft_price
    result["soft_market_confidence"] = soft_confidence
    result["soft_market_samples"] = sample_count
    result["cap_reduction_pct"] = cap_reduction_pct
    
    # Add marker to strategy_reason
    marker = f" | soft_market_cap: {original_resale:.2f} → {soft_cap:.2f} CHF (-{cap_reduction_pct:.0f}%, {sample_count} samples)"
    result["strategy_reason"] = result.get("strategy_reason", "") + marker
    
    return result


# ==============================================================================
# PROFIT & STRATEGY
# ==============================================================================

def calculate_profit(resale_price: float, purchase_price: float) -> float:
    """
    Calculate expected profit after fees and shipping.
    
    VALIDATION GATE: Ensures positive prices before calculation.
    """
    if resale_price <= 0 or purchase_price <= 0:
        return 0.0
    return round(resale_price * (1 - RICARDO_FEE_PERCENT) - purchase_price - SHIPPING_COST_CHF, 2)


def validate_price_sanity(new_price: Optional[float], resale_price: Optional[float], context: str = "") -> bool:
    """
    PHASE 6: VALIDATION GATE - Price Sanity Checks
    
    Ensures pricing data is logically consistent:
    - Resale price must be <= new price (used items can't cost more than new)
    - Both prices must be positive if present
    
    Args:
        new_price: New/retail price
        resale_price: Expected resale/used price
        context: Where this validation is happening (for logging)
    
    Returns:
        True if prices are valid, False otherwise
    """
    if new_price is not None and new_price <= 0:
        print(f"   VALIDATION FAILED ({context}): new_price={new_price} must be positive")
        return False
    
    if resale_price is not None and resale_price <= 0:
        print(f"   VALIDATION FAILED ({context}): resale_price={resale_price} must be positive")
        return False
    
    # Critical check: Resale can never exceed new price
    if new_price and resale_price and resale_price > new_price:
        print(f"   VALIDATION FAILED ({context}): resale_price={resale_price:.2f} > new_price={new_price:.2f}")
        print(f"      This violates basic economics (used > new). Capping resale to 85% of new.")
        return False
    
    return True


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
    all_listings_for_variant: Optional[List[Dict[str, Any]]] = None,
    search_identity: Optional[str] = None,
    conn=None,
    run_id: str = None,
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
    
    # PHASE 6: VALIDATION GATE - Price Sanity Checks
    if result["resale_price_est"] and result["new_price"]:
        # Validate prices are logically consistent
        if not validate_price_sanity(result["new_price"], result["resale_price_est"], context="deal_evaluation"):
            # Validation failed - cap resale to 85% of new price
            result["resale_price_est"] = result["new_price"] * 0.85
        
        # Additional cap: Resale price ≤ 70% of new price (used items reality)
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
    
    # SOFT MARKET PRICING: Apply conservative market reality cap
    # Uses AI-normalized search_identity (same as Websearch) for consistent aggregation
    # Only applies if hard market pricing is unavailable and we have ≥2 listings with bids
    if search_identity and all_listings_for_variant and not result.get("market_based_resale"):
        soft_market_data = calculate_soft_market_price(search_identity, all_listings_for_variant)
        if soft_market_data:
            # Apply soft market cap (CEILING ONLY - never increases profit)
            result = apply_soft_market_cap(result, soft_market_data, search_identity)
            
            # Observability logging
            if result.get('soft_market_cap_applied'):
                # Calculate avg_bid for logging
                samples = soft_market_data.get('samples', [])
                avg_bid = sum(samples) / len(samples) if samples else 0
                
                print(f"   SOFT MARKET CAP APPLIED")
                print(f"      identity={search_identity}")
                print(f"      soft_price={result.get('soft_market_price', 0):.2f}")
                print(f"      samples={result.get('soft_market_samples', 0)}")
                print(f"      avg_bid={avg_bid:.2f}")
                print(f"      original_resale={result.get('original_resale_before_cap', 0):.2f}")
        else:
            # Guard log: soft market skipped
            listings_with_bids = sum(1 for l in all_listings_for_variant if l.get('bids_count', 0) > 0)
            if listings_with_bids > 0:
                print(f"   SOFT MARKET SKIPPED: reason=insufficient_bid_samples (need ≥2, have {listings_with_bids})")
                print(f"      identity={search_identity}")
    elif search_identity and not result.get("market_based_resale"):
        # Guard log: no search identity listings available
        if all_listings_for_variant is None:
            print(f"   SOFT MARKET SKIPPED: reason=no_listings_fetched")
            print(f"      identity={search_identity}")
        elif len(all_listings_for_variant) == 0:
            print(f"   SOFT MARKET SKIPPED: reason=no_persisted_listings_for_identity")
            print(f"      identity={search_identity}")
    
    # CRITICAL: Preserve soft market marker before strategy determination
    # Bug fix: determine_strategy() overwrites strategy_reason, losing soft market marker
    soft_market_marker = ""
    if result.get('soft_market_cap_applied'):
        # Extract soft market marker from current strategy_reason
        current_reason = result.get('strategy_reason', '')
        if ' | soft_market_cap:' in current_reason:
            marker_start = current_reason.find(' | soft_market_cap:')
            soft_market_marker = current_reason[marker_start:]
            print(f"   SOFT MARKET MARKER PRESERVED: {soft_market_marker[:80]}...")
    
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
    
    # PHASE 3 (v8.0): BUNDLE DETECTION & PRICING
    # Uses new extraction/bundle_extractor.py with German-aware prompts
    # and price_bundle_components_v2 with market data integration
    if BUNDLE_ENABLED and looks_like_bundle(title, description):
        print(f"\n   BUNDLE DETECTION triggered for: {title[:60]}...")
        
        try:
            from extraction.bundle_extractor import extract_bundle_components
            from models.bundle_component import BundleComponent
            
            # Detect category from query_analysis
            category = _get_category(query_analysis)
            
            # COST OPTIMIZATION: Pass v10 products to avoid duplicate AI call
            v10_products = None
            if batch_bundle_result and batch_bundle_result.get("products"):
                v10_products = batch_bundle_result.get("products")
            
            # Extract bundle components using German-aware prompts
            bundle_extraction = extract_bundle_components(
                title=title,
                description=description,
                category=category,
                image_url=image_url,
                use_vision=False,  # First pass: no vision
                call_ai_func=call_ai,
                v10_products=v10_products,  # Reuse v10 extraction if available
            )
            
            # If extraction confidence is low and vision is enabled, use vision
            if bundle_extraction.is_bundle and bundle_extraction.confidence < 0.7 and BUNDLE_USE_VISION and image_url:
                print(f"      Low confidence ({bundle_extraction.confidence:.2f}), trying vision...")
                vision_extraction = extract_bundle_components(
                    title=title,
                    description=description,
                    category=category,
                    image_url=image_url,
                    use_vision=True,
                    call_ai_func=call_ai,
                )
                if vision_extraction.confidence > bundle_extraction.confidence:
                    bundle_extraction = vision_extraction
                    print(f"      Vision improved confidence to {vision_extraction.confidence:.2f}")
            
            if bundle_extraction.is_bundle and len(bundle_extraction.components) >= 2:
                print(f"   Bundle detected: {len(bundle_extraction.components)} components")
                result["is_bundle"] = True
                result["bundle_extraction_method"] = bundle_extraction.extraction_method
                
                # Price components using market data + weight-based fallbacks
                priced_components = price_bundle_components_v2(
                    components=bundle_extraction.components,
                    category=bundle_extraction.category or category,
                    query_analysis=query_analysis,
                    conn=conn,
                    run_id=run_id,
                )
                
                # Validate: Need at least 2 priced components
                if not priced_components or len(priced_components) < 2:
                    component_count = len(priced_components) if priced_components else 0
                    print(f"   Only {component_count} priced component(s) — treating as single product")
                    result["is_bundle"] = False
                else:
                    # Calculate bundle totals
                    total_new = sum(c.new_price * c.quantity for c in priced_components if c.new_price)
                    total_resale = sum(c.unit_value for c in priced_components if c.unit_value)
                    
                    # Apply bundle discount (harder to sell as bundle)
                    bundle_resale = total_resale * (1 - BUNDLE_DISCOUNT_PERCENT)
                    
                    # Cap at max percent of new price
                    if total_new > 0:
                        max_resale = total_new * MAX_BUNDLE_RESALE_PERCENT_OF_NEW
                        bundle_resale = min(bundle_resale, max_resale)
                    
                    result["resale_price_bundle"] = round(bundle_resale, 2)
                    result["resale_price_est"] = round(bundle_resale, 2)
                    result["new_price"] = round(total_new, 2)
                    result["price_source"] = PRICE_SOURCE_BUNDLE_AGGREGATE
                    
                    # Store components for DB persistence
                    result["bundle_components"] = [c.to_dict() for c in priced_components]
                    result["bundle_total_weight_kg"] = bundle_extraction.total_weight_kg
                    
                    # Recalculate expected profit with bundle pricing
                    result["expected_profit"] = calculate_profit(bundle_resale, purchase_price)
                    
                    print(f"   📊 Bundle pricing: new={total_new:.2f}, resale={bundle_resale:.2f} CHF")
            else:
                print(f"   ❌ Not a bundle or insufficient components")
                
        except ImportError as e:
            print(f"   ⚠️ Bundle extraction import failed: {e}")
        except Exception as e:
            print(f"   ⚠️ Bundle extraction failed: {e}")
    
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
    
    # CRITICAL: Re-append soft market marker after strategy determination
    # This ensures soft market effects are persisted to DB
    if soft_market_marker:
        result["strategy_reason"] = result["strategy_reason"] + soft_market_marker
        print(f"   ✅ SOFT MARKET MARKER RESTORED: strategy_reason now contains soft_market_cap marker")
    
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
        notes.append(f" Market ({result['market_sample_size']} samples)")
    if result["is_bundle"]:
        notes.append(f" Bundle ({len(result.get('bundle_components', []))} items)")
    if result["price_source"].startswith("web_"):
        notes.append(f" Web price ({result['price_source']})")
    notes.append(f"Strategy: {strategy}")
    result["ai_notes"] = " | ".join(notes)
    
    # DEFENSIVE ASSERTION: Verify soft market marker persistence
    # This ensures the persistence bug is caught if it reoccurs
    if result.get('soft_market_cap_applied'):
        final_reason = result.get('strategy_reason', '')
        if 'soft_market_cap' not in final_reason:
            print(f"   ASSERT FAILED: soft_market applied but strategy_reason missing marker!")
            print(f"      strategy_reason: {final_reason}")
            print(f"      This indicates a persistence bug - marker was lost before DB write")
            # Force marker back in as emergency fallback
            if soft_market_marker:
                result['strategy_reason'] = final_reason + soft_market_marker
                print(f"      Emergency fix applied: marker restored")
    
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
    global BUNDLE_USE_VISION, BUNDLE_ALWAYS_SCRAPE_DETAIL
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
    val = get_nested("bundle", "use_vision_for_unclear", None)
    if val is not None:
        BUNDLE_USE_VISION = val
    val = get_nested("bundle", "always_scrape_detail", None)
    if val is not None:
        BUNDLE_ALWAYS_SCRAPE_DETAIL = val
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
    
    # v8.1: Sync MIN_PROFIT_THRESHOLD to extracted module
    set_min_profit_threshold(MIN_PROFIT_THRESHOLD)
    
    # v8.1: Sync bundle config to extracted module
    set_bundle_config(MAX_COMPONENT_PRICE, BUNDLE_DISCOUNT_PERCENT, MAX_BUNDLE_RESALE_PERCENT_OF_NEW)