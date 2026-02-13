"""
Core AI client module - unified AI call wrapper.
Extracted from ai_filter.py v8.0
"""

from typing import Optional

# Module-level state (set by ai_filter.py)
_claude_client = None
_openai_client = None
_config = None
_provider = "claude"

# Cost tracking
RUN_COST_USD: float = 0.0
DAILY_COST_LIMIT: float = 5.0

# Cost constants
COST_CLAUDE_HAIKU = 0.002
COST_CLAUDE_WEB_SEARCH = 0.015
COST_VISION = 0.005


def init_clients(claude_client, openai_client, config, provider: str = "claude"):
    """Initialize AI clients from ai_filter."""
    global _claude_client, _openai_client, _config, _provider
    _claude_client = claude_client
    _openai_client = openai_client
    _config = config
    _provider = provider


def set_cost_limit(limit: float):
    """Set daily cost limit."""
    global DAILY_COST_LIMIT
    DAILY_COST_LIMIT = limit


def add_cost(amount: float):
    """Add to running cost total."""
    global RUN_COST_USD
    RUN_COST_USD += amount


def get_run_cost() -> float:
    """Get current run cost."""
    return RUN_COST_USD


def reset_cost():
    """Reset run cost to zero."""
    global RUN_COST_USD
    RUN_COST_USD = 0.0


def is_budget_exceeded() -> bool:
    """Check if daily budget is exceeded."""
    return RUN_COST_USD >= DAILY_COST_LIMIT


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
    """
    if not _claude_client:
        return None
    
    if not _config:
        raise RuntimeError("AI Client not initialized. Call init_clients() first.")
    
    # Select model from config
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
        
        # Extract text from response
        result_parts = []
        for block in response.content:
            if hasattr(block, 'text'):
                result_parts.append(block.text)
        
        return "\n".join(result_parts) if result_parts else None
        
    except Exception as e:
        error_str = str(e)
        
        runtime_mode = getattr(_config.runtime, 'mode', 'unknown')
        error_type = "rate_limit" if ("429" in error_str or "rate_limit" in error_str.lower()) else "api_error"
        
        print(f"\nAI_FAILURE:")
        print(f"  step: {step}")
        print(f"  model: {selected_model}")
        print(f"  runtime_mode: {runtime_mode}")
        print(f"  error_type: {error_type}")
        print(f"  error_message: {str(e)[:100]}")
        
        if error_type == "rate_limit":
            print(f"  action_taken: re-raise (retry logic will handle)")
            raise
        
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
        raise RuntimeError("AI Client not initialized. Call init_clients() first.")
    
    selected_model = model or _config.ai.openai_model
    
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
    step: str = "unknown",
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
            step=step,
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
            step=step,
        )
    
    return None
