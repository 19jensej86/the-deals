"""
Config Loader - v7.0 (Claude Edition + Detail Scraping)
=======================================================
Loads configuration from configs/config.yaml with support for:
- Database settings (including clear_on_start)
- Cache settings (enabled, clear_on_start)
- Profit settings (fees, shipping, threshold)
- Bundle detection settings
- AI settings (Claude PRIMARY, OpenAI fallback)
- Web Search settings
- Detail page scraping settings (NEW)
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PGConf:
    """PostgreSQL connection settings"""
    host: str
    port: int
    db: str
    user: str
    password: str


@dataclass
class RuntimeConf:
    """Runtime mode settings"""
    mode: str = "testing"  # "testing" or "normal"


@dataclass
class DBConf:
    """Database behavior settings"""
    clear_on_start: bool = True


@dataclass
class CacheConf:
    """Cache behavior settings"""
    enabled: bool = True
    clear_on_start: bool = True
    variant_cache_days: int = 30
    component_cache_days: int = 30
    cluster_cache_days: int = 7
    web_price_cache_days: int = 60


@dataclass
class ProfitConf:
    """Profit calculation settings"""
    ricardo_fee_percent: float = 0.10
    shipping_cost_chf: float = 0.0
    min_profit_threshold: float = 20.0


@dataclass
class BundleConf:
    """Bundle detection settings"""
    enabled: bool = True
    discount_percent: float = 0.10
    min_component_value: float = 10.0
    use_vision_for_unclear: bool = True


@dataclass
class GeneralConf:
    """General application settings"""
    user_agent: str
    request_timeout_sec: int
    max_pages_list: int
    exclude_terms: List[str]
    autoclean_days: Optional[int] = None
    max_listings_per_query: Optional[int] = None
    car_model: str = "VW Touran"
    # v7.0: Detail page scraping settings
    detail_pages_enabled: bool = False
    max_detail_pages_per_run: int = 5


@dataclass
class WebSearchConf:
    """v7.0: Web Search configuration"""
    enabled: bool = True
    preferred_shops: List[str] = field(default_factory=lambda: ["digitec.ch", "galaxus.ch"])
    clothing_shops: List[str] = field(default_factory=lambda: ["zalando.ch", "manor.ch"])


@dataclass
class AIConf:
    """v7.0: AI settings - Claude PRIMARY, OpenAI fallback"""
    # Provider selection
    provider: str = "claude"  # "claude" or "openai"
    
    # Claude models
    claude_model_fast: str = "claude-haiku-4-5-20241022"
    claude_model_web: str = "claude-sonnet-4-20250514"
    
    # OpenAI fallback
    openai_model: str = "gpt-4o-mini"
    
    # General settings
    use_ai_text: bool = True
    use_ai_vision: bool = True
    temperature: float = 0.2
    adaptive_vision_rate: float = 0.10
    
    # Web search settings
    web_search: WebSearchConf = field(default_factory=WebSearchConf)
    
    # Pricing
    pricing: Dict[str, float] = field(default_factory=dict)
    
    # Budget
    budget: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Cfg:
    """Main configuration container"""
    general: GeneralConf
    pg: PGConf
    runtime: RuntimeConf
    db: DBConf
    cache: CacheConf
    profit: ProfitConf
    bundle: BundleConf
    search: Dict[str, Any]
    ai: AIConf


def load_config() -> Cfg:
    """
    Loads configuration from YAML file.
    
    Searches for config in multiple locations:
    1. configs/config.yaml (relative to working dir)
    2. config.yaml (relative to working dir)
    3. configs/config.yaml (relative to this file)
    """
    config_paths = [
        "configs/config.yaml",
        "config.yaml",
        os.path.join(os.path.dirname(__file__), "configs/config.yaml"),
    ]
    
    config_path = None
    for path in config_paths:
        if os.path.exists(path):
            config_path = path
            break
    
    if not config_path:
        raise FileNotFoundError(f"Config file not found in: {config_paths}")
    
    print(f"📁 Loading config from: {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)

    # Parse sections
    general = y.get("general", {})
    pg = y.get("postgres", {})
    runtime = y.get("runtime", {})
    db = y.get("db", {})
    cache = y.get("cache", {})
    profit = y.get("profit", {})
    bundle = y.get("bundle", {})
    ai = y.get("ai", {})
    web_search = ai.get("web_search", {})

    return Cfg(
        general=GeneralConf(
            user_agent=general.get("user_agent", "Mozilla/5.0"),
            request_timeout_sec=int(general.get("request_timeout_sec", 15)),
            max_pages_list=int(general.get("max_pages_list", 2)),
            exclude_terms=general.get("exclude_terms", []),
            autoclean_days=general.get("autoclean_days"),
            max_listings_per_query=general.get("max_listings_per_query"),
            car_model=general.get("car_model", "VW Touran"),
            # v7.0: Detail page settings
            detail_pages_enabled=general.get("detail_pages_enabled", False),
            max_detail_pages_per_run=int(general.get("max_detail_pages_per_run", 5)),
        ),
        pg=PGConf(
            host=pg.get("host", "localhost"),
            port=int(pg.get("port", 5432)),
            db=pg.get("db", "dealfinder"),
            user=pg.get("user", "dealuser"),
            password=pg.get("password", ""),
        ),
        runtime=RuntimeConf(
            mode=runtime.get("mode", "testing"),
        ),
        db=DBConf(
            clear_on_start=db.get("clear_on_start", False),
        ),
        cache=CacheConf(
            enabled=cache.get("enabled", True),
            clear_on_start=cache.get("clear_on_start", False),
            variant_cache_days=cache.get("variant_cache_days", 30),
            component_cache_days=cache.get("component_cache_days", 30),
            cluster_cache_days=cache.get("cluster_cache_days", 7),
            web_price_cache_days=cache.get("web_price_cache_days", 60),
        ),
        profit=ProfitConf(
            ricardo_fee_percent=float(profit.get("ricardo_fee_percent", 0.10)),
            shipping_cost_chf=float(profit.get("shipping_cost_chf", 0.0)),
            min_profit_threshold=float(profit.get("min_profit_threshold", 20.0)),
        ),
        bundle=BundleConf(
            enabled=bundle.get("enabled", True),
            discount_percent=float(bundle.get("discount_percent", 0.10)),
            min_component_value=float(bundle.get("min_component_value", 10.0)),
            use_vision_for_unclear=bundle.get("use_vision_for_unclear", True),
        ),
        search=y.get("search", {"queries": []}),
        ai=AIConf(
            provider=ai.get("provider", "claude"),
            claude_model_fast=ai.get("claude_model_fast", "claude-haiku-4-5-20241022"),
            claude_model_web=ai.get("claude_model_web", "claude-sonnet-4-20250514"),
            openai_model=ai.get("openai_model", "gpt-4o-mini"),
            use_ai_text=ai.get("use_ai_text", True),
            use_ai_vision=ai.get("use_ai_vision", False),
            temperature=float(ai.get("temperature", 0.3)),
            adaptive_vision_rate=ai.get("adaptive_vision_rate", 0.10),
            web_search=WebSearchConf(
                enabled=web_search.get("enabled", True),
                preferred_shops=web_search.get("preferred_shops", ["digitec.ch", "galaxus.ch"]),
                clothing_shops=web_search.get("clothing_shops", ["zalando.ch", "manor.ch"]),
            ),
            pricing=ai.get("pricing", {}),
            budget=ai.get("budget", {}),
        ),
    )


def print_config_summary(cfg: Cfg):
    """Prints a summary of loaded configuration"""
    print("\n" + "=" * 60)
    print("📋 Configuration Summary - v7.0 (Claude + Detail Scraping)")
    print("=" * 60)
    print(f"  AI Provider:      {cfg.ai.provider.upper()}")
    if cfg.ai.provider == "claude":
        print(f"  Claude Fast:      {cfg.ai.claude_model_fast}")
        print(f"  Claude Web:       {cfg.ai.claude_model_web}")
    else:
        print(f"  OpenAI Model:     {cfg.ai.openai_model}")
    print(f"  Web Search:       {'ENABLED ✅' if cfg.ai.web_search.enabled else 'DISABLED'}")
    print(f"  Vision enabled:   {cfg.ai.use_ai_vision}")
    print("-" * 60)
    print(f"  Car model:        {cfg.general.car_model}")
    print(f"  Max pages:        {cfg.general.max_pages_list}")
    print(f"  Max per query:    {cfg.general.max_listings_per_query}")
    print(f"  Runtime mode:     {cfg.runtime.mode.upper()}")
    print(f"  DB clear start:   {cfg.db.clear_on_start}")
    print(f"  Cache enabled:    {cfg.cache.enabled}")
    print(f"  Cache clear:      {cfg.cache.clear_on_start}")
    print(f"  Bundle enabled:   {cfg.bundle.enabled}")
    print(f"  Bundle discount:  {cfg.bundle.discount_percent * 100:.0f}%")
    print(f"  Ricardo fee:      {cfg.profit.ricardo_fee_percent * 100:.0f}%")
    print(f"  Shipping cost:    {cfg.profit.shipping_cost_chf} CHF")
    print(f"  Min profit:       {cfg.profit.min_profit_threshold} CHF")
    print("-" * 60)
    # v7.0: Detail scraping settings
    print(f"  Detail pages:     {'ENABLED ✅' if cfg.general.detail_pages_enabled else 'DISABLED'}")
    print(f"  Max detail pages: {cfg.general.max_detail_pages_per_run}")
    print("-" * 60)
    print(f"  Queries:          {cfg.search.get('queries', [])}")
    print("=" * 60 + "\n")