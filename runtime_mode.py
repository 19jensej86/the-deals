"""
Runtime Mode Configuration - SINGLE SOURCE OF TRUTH
====================================================
Zentrales Modul für Test vs. Prod Verhalten.

WICHTIG: Kein Modul darf eigene Interpretation haben!
Alle Entscheidungen werden hier getroffen.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class RuntimeMode(Enum):
    """Runtime mode: test or prod"""
    TEST = "test"
    PROD = "prod"


@dataclass
class ModeConfig:
    """
    Zentrale Konfiguration basierend auf Runtime Mode.
    
    ALLE Module müssen diese Config verwenden!
    """
    mode: RuntimeMode
    
    # Database behavior
    truncate_on_start: bool
    truncate_tables: list[str]
    
    # Websearch behavior
    websearch_enabled: bool
    max_websearch_calls: int
    websearch_wait_seconds: int
    
    # Retry behavior
    retry_enabled: bool
    max_retries: int
    
    # Cache behavior
    cache_enabled: bool
    cache_clear_on_start: bool
    
    # Price source preferences
    prefer_ai_fallback: bool
    prefer_query_baseline: bool
    
    # Budget limits
    max_run_cost_usd: float
    enforce_budget: bool


def get_mode_config(mode: str) -> ModeConfig:
    """
    Gibt die komplette Konfiguration für einen Mode zurück.
    
    Args:
        mode: "test" oder "prod"
    
    Returns:
        ModeConfig mit allen Einstellungen
    
    Raises:
        ValueError: Wenn mode ungültig ist
    """
    if mode not in ["test", "prod"]:
        raise ValueError(f"Invalid mode: {mode}. Must be 'test' or 'prod'")
    
    runtime_mode = RuntimeMode.TEST if mode == "test" else RuntimeMode.PROD
    
    if runtime_mode == RuntimeMode.TEST:
        return ModeConfig(
            mode=runtime_mode,
            
            # 🧪 TEST: TRUNCATE EVERYTHING
            truncate_on_start=True,
            truncate_tables=[
                "listings",
                "price_history", 
                "component_cache",
                "market_data",
                "bundle_components",
            ],
            
            # 🧪 TEST: MINIMAL WEBSEARCH
            websearch_enabled=True,  # Erlaubt, aber stark limitiert
            max_websearch_calls=1,   # MAX 1 CALL!
            websearch_wait_seconds=0,  # KEIN WAIT in Test
            
            # 🧪 TEST: NO RETRIES
            retry_enabled=False,
            max_retries=0,
            
            # 🧪 TEST: NO CACHE
            cache_enabled=False,
            cache_clear_on_start=True,
            
            # 🧪 TEST: PREFER CHEAP FALLBACKS
            prefer_ai_fallback=True,
            prefer_query_baseline=True,
            
            # 🧪 TEST: STRICT BUDGET
            max_run_cost_usd=0.20,  # MAX 20 CENTS!
            enforce_budget=True,     # HARD STOP
        )
    
    else:  # PROD
        return ModeConfig(
            mode=runtime_mode,
            
            # 🚀 PROD: NO TRUNCATE
            truncate_on_start=False,
            truncate_tables=[],
            
            # 🚀 PROD: FULL WEBSEARCH
            websearch_enabled=True,
            max_websearch_calls=50,      # Generous limit
            websearch_wait_seconds=120,  # Rate limit protection
            
            # 🚀 PROD: LIMITED RETRIES
            retry_enabled=True,
            max_retries=1,  # MAX 1 retry per batch
            
            # 🚀 PROD: CACHE ENABLED
            cache_enabled=True,
            cache_clear_on_start=False,
            
            # 🚀 PROD: PREFER WEB PRICES
            prefer_ai_fallback=False,
            prefer_query_baseline=False,
            
            # 🚀 PROD: REASONABLE BUDGET
            max_run_cost_usd=5.00,  # $5 max per run
            enforce_budget=True,
        )


def should_truncate_db(mode_config: ModeConfig) -> bool:
    """Soll die DB geleert werden?"""
    return mode_config.truncate_on_start


def should_use_websearch(mode_config: ModeConfig, current_calls: int) -> bool:
    """
    Soll Websearch verwendet werden?
    
    Args:
        mode_config: Runtime config
        current_calls: Anzahl bisheriger Websearch calls
    
    Returns:
        True wenn Websearch erlaubt ist
    """
    if not mode_config.websearch_enabled:
        return False
    
    if current_calls >= mode_config.max_websearch_calls:
        return False
    
    return True


def should_retry(mode_config: ModeConfig, retry_count: int) -> bool:
    """
    Soll ein Retry gemacht werden?
    
    Args:
        mode_config: Runtime config
        retry_count: Anzahl bisheriger Retries
    
    Returns:
        True wenn Retry erlaubt ist
    """
    if not mode_config.retry_enabled:
        return False
    
    if retry_count >= mode_config.max_retries:
        return False
    
    return True


def is_budget_exceeded(mode_config: ModeConfig, current_cost: float) -> bool:
    """
    Ist das Budget überschritten?
    
    Args:
        mode_config: Runtime config
        current_cost: Aktuelle Kosten in USD
    
    Returns:
        True wenn Budget überschritten
    """
    if not mode_config.enforce_budget:
        return False
    
    return current_cost >= mode_config.max_run_cost_usd


def get_wait_seconds(mode_config: ModeConfig) -> int:
    """Wie lange soll vor Websearch gewartet werden?"""
    return mode_config.websearch_wait_seconds


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    # Test mode
    test_config = get_mode_config("test")
    print("🧪 TEST MODE:")
    print(f"  Truncate DB: {test_config.truncate_on_start}")
    print(f"  Max websearch: {test_config.max_websearch_calls}")
    print(f"  Max cost: ${test_config.max_run_cost_usd}")
    print(f"  Retries: {test_config.retry_enabled}")
    print()
    
    # Prod mode
    prod_config = get_mode_config("prod")
    print("🚀 PROD MODE:")
    print(f"  Truncate DB: {prod_config.truncate_on_start}")
    print(f"  Max websearch: {prod_config.max_websearch_calls}")
    print(f"  Max cost: ${prod_config.max_run_cost_usd}")
    print(f"  Retries: {prod_config.retry_enabled}")
