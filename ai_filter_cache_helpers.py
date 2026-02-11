"""
Cache helper functions for ai_filter.py
Separated to avoid circular imports and maintain clean architecture.
"""
from typing import Dict, Optional
from datetime import datetime, timedelta
import json
import os


# Cache dictionaries (imported from ai_filter.py)
_web_price_cache: Dict[str, Dict] = {}
_variant_cache: Dict[str, Dict] = {}

WEB_PRICE_CACHE_FILE = "web_price_cache.json"
WEB_PRICE_CACHE_DAYS = 60
VARIANT_CACHE_FILE = "variant_cache.json"
VARIANT_CACHE_DAYS = 30


def get_cached_web_price(variant_key: str) -> Optional[Dict]:
    """
    Get cached web price for a variant.
    
    Returns:
        Dict with new_price, price_source, shop_name if cached and not expired
        None if not cached or expired
    """
    if not variant_key or variant_key not in _web_price_cache:
        return None
    
    cached = _web_price_cache[variant_key]
    cached_time = cached.get("cached_at")
    
    if not cached_time:
        return None
    
    # Check if expired
    try:
        cached_dt = datetime.fromisoformat(cached_time)
        age_days = (datetime.now() - cached_dt).days
        
        if age_days > WEB_PRICE_CACHE_DAYS:
            return None
    except:
        return None
    
    return {
        "new_price": cached.get("new_price"),
        "price_source": cached.get("price_source"),
        "shop_name": cached.get("shop_name"),
    }


def set_cached_web_price(variant_key: str, new_price: float, price_source: str, shop_name: str):
    """
    Cache web price for a variant.
    """
    if not variant_key:
        return
    
    _web_price_cache[variant_key] = {
        "new_price": new_price,
        "price_source": price_source,
        "shop_name": shop_name,
        "cached_at": datetime.now().isoformat(),
    }
    
    # Persist to file
    try:
        with open(WEB_PRICE_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_web_price_cache, f, indent=2, ensure_ascii=False)
    except:
        pass


def get_cached_variant_info(variant_key: str) -> Optional[Dict]:
    """
    Get cached variant info (new_price, resale_price, transport).
    
    Returns:
        Dict with variant info if cached and not expired
        None if not cached or expired
    """
    if not variant_key or variant_key not in _variant_cache:
        return None
    
    cached = _variant_cache[variant_key]
    cached_time = cached.get("cached_at")
    
    if not cached_time:
        return None
    
    # Check if expired
    try:
        cached_dt = datetime.fromisoformat(cached_time)
        age_days = (datetime.now() - cached_dt).days
        
        if age_days > VARIANT_CACHE_DAYS:
            return None
    except:
        return None
    
    return cached


def set_cached_variant_info(variant_key: str, new_price: float, transport_car: bool, 
                            resale_price: float, market_based: bool, market_sample_size: int):
    """
    Cache variant info.
    """
    if not variant_key:
        return
    
    _variant_cache[variant_key] = {
        "new_price": new_price,
        "transport_car": transport_car,
        "resale_price": resale_price,
        "market_based": market_based,
        "market_sample_size": market_sample_size,
        "cached_at": datetime.now().isoformat(),
    }
    
    # Persist to file
    try:
        with open(VARIANT_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_variant_cache, f, indent=2, ensure_ascii=False)
    except:
        pass


def load_caches():
    """Load caches from disk."""
    global _web_price_cache, _variant_cache
    
    # Load web price cache
    if os.path.exists(WEB_PRICE_CACHE_FILE):
        try:
            with open(WEB_PRICE_CACHE_FILE, 'r', encoding='utf-8') as f:
                _web_price_cache = json.load(f)
        except:
            _web_price_cache = {}
    
    # Load variant cache
    if os.path.exists(VARIANT_CACHE_FILE):
        try:
            with open(VARIANT_CACHE_FILE, 'r', encoding='utf-8') as f:
                _variant_cache = json.load(f)
        except:
            _variant_cache = {}
