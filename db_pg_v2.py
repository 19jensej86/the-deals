"""
Database Manager - v2.2 (Schema v2.2 FINAL)
============================================
Complete rewrite for normalized schema with:
- products (stable product identity)
- listings (raw marketplace facts)
- deals (immutable evaluations per run)
- bundles (first-class bundle entities)
- bundle_items (bundle components)
- runs (pipeline execution metadata)
- deal_audit / bundle_audit (pipeline metadata)
- price_cache (temporary websearch results)
- price_history (auction price tracking)
- user_actions (user decisions)

PostgreSQL database operations with UUID run_id, TIMESTAMPTZ, NUMERIC(12,2).
"""

import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import json
import uuid
import re
from typing import Dict, List, Any, Optional, Union
from datetime import datetime


SCHEMA_VERSION = "v2.2"


# ==============================================================================
# UUID VALIDATION (FAIL-FAST)
# ==============================================================================

def assert_valid_uuid(run_id: Union[str, uuid.UUID], context: str = "") -> str:
    """
    Validates that run_id is a valid UUID string.
    Fails fast with clear error message.
    
    Args:
        run_id: UUID string or UUID object
        context: Where this validation is happening (for error messages)
    
    Returns:
        Normalized UUID string
        
    Raises:
        ValueError: If run_id is not a valid UUID
    """
    if isinstance(run_id, uuid.UUID):
        return str(run_id)
    
    if not isinstance(run_id, str):
        raise ValueError(
            f" INVALID run_id TYPE in {context}: "
            f"Expected UUID string, got {type(run_id).__name__}"
        )
    
    try:
        # Validate by parsing
        uuid_obj = uuid.UUID(run_id)
        return str(uuid_obj)
    except (ValueError, AttributeError) as e:
        raise ValueError(
            f" INVALID run_id FORMAT in {context}: '{run_id}'\n"
            f"   Expected: UUID (e.g., 'd41ef124-...')\n"
            f"   Got: {run_id}\n"
            f"   Error: {e}\n"
            f"   Hint: Legacy timestamp detected? Check for datetime.strftime() calls"
        )


# ==============================================================================
# CONNECTION
# ==============================================================================

def get_conn(pg_cfg):
    """
    Creates PostgreSQL connection.
    Accepts PGConf dataclass OR dict.
    """
    if hasattr(pg_cfg, "host"):
        host = pg_cfg.host
        port = pg_cfg.port
        db = pg_cfg.db
        user = pg_cfg.user
        password = pg_cfg.password
    else:
        host = pg_cfg.get("host")
        port = pg_cfg.get("port")
        db = pg_cfg.get("db")
        user = pg_cfg.get("user")
        password = pg_cfg.get("password")

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=db,
        user=user,
        password=password,
    )
    conn.autocommit = True
    print(f"🔧 DB connected → {user}@{host}:{port}/{db}")
    return conn


# ==============================================================================
# SCHEMA VERIFICATION (v2.2 schema is created via SQL file, not Python)
# ==============================================================================

def ensure_schema(conn):
    """
    Verifies that v2.2 schema exists.
    Schema should be created via schema_v2.2_FINAL.sql + patch files.
    This function only validates, does not create tables.
    """
    required_tables = [
        'products', 'product_aliases', 'listings', 'deals', 'bundles',
        'bundle_items', 'user_actions', 'runs', 'deal_audit', 'bundle_audit',
        'price_cache', 'price_history'
    ]
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        existing_tables = {row[0] for row in cur.fetchall()}
    
    missing = [t for t in required_tables if t not in existing_tables]
    
    if missing:
        raise RuntimeError(
            f"❌ Schema v2.2 not properly installed!\n"
            f"Missing tables: {', '.join(missing)}\n"
            f"Run: psql -f schema_v2.2_FINAL.sql && psql -f schema_v2.2.2_PATCH.sql"
        )
    
    print(f"✅ Schema v2.2 verified ({len(required_tables)} tables)")


def ensure_schema_v2(conn, reset_schema: bool = False):
    """Alias for backward compatibility. Use ensure_schema()."""
    ensure_schema(conn)


# ==============================================================================
# VARIANT KEY NORMALIZATION (matches database function)
# ==============================================================================

def normalize_variant_key(key: str) -> str:
    """
    Normalize variant_key to match database function:
    - lowercase
    - trim whitespace
    - replace whitespace with underscores
    - remove non [a-z0-9_] characters
    - collapse multiple underscores
    - trim leading/trailing underscores
    """
    if not key:
        return ""
    
    # Step 1: Lowercase and trim
    normalized = key.lower().strip()
    
    # Step 2: Replace whitespace with underscores
    normalized = re.sub(r'\s+', '_', normalized)
    
    # Step 3: Remove non-alphanumeric characters (keep only a-z, 0-9, _)
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    
    # Step 4: Collapse multiple underscores
    normalized = re.sub(r'_+', '_', normalized)
    
    # Step 5: Trim leading/trailing underscores
    normalized = normalized.strip('_')
    
    return normalized


# ==============================================================================
# RUN MANAGEMENT
# ==============================================================================

def start_run(conn, mode: str, queries: List[str] = None) -> str:
    """
    Creates a new run record and returns the run_id (UUID).
    
    Args:
        conn: Database connection
        mode: 'test' or 'prod'
        queries: List of search queries for this run
    
    Returns:
        run_id (UUID string)
    """
    run_id = str(uuid.uuid4())
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO runs (id, mode, queries, status, started_at)
            VALUES (%s, %s, %s, 'running', NOW())
        """, (run_id, mode, json.dumps(queries) if queries else None))
    
    print(f"🚀 Run started: {run_id[:8]}... (mode={mode})")
    return run_id


def finish_run(
    conn, 
    run_id: str, 
    listings_found: int = 0,
    deals_created: int = 0,
    bundles_created: int = 0,
    profitable_deals: int = 0,
    ai_cost_usd: float = 0,
    websearch_calls: int = 0,
    error_message: str = None
):
    """
    Marks a run as completed and records final statistics.
    """
    status = 'failed' if error_message else 'completed'
    
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE runs SET
                finished_at = NOW(),
                duration_sec = EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER,
                status = %s,
                listings_found = %s,
                deals_created = %s,
                bundles_created = %s,
                profitable_deals = %s,
                ai_cost_usd = %s,
                websearch_calls = %s,
                error_message = %s
            WHERE id = %s
        """, (
            status, listings_found, deals_created, bundles_created,
            profitable_deals, ai_cost_usd, websearch_calls, error_message, run_id
        ))
    
    icon = "❌" if error_message else "✅"
    print(f"{icon} Run finished: {run_id[:8]}... ({status})")


def get_latest_run_id(conn) -> Optional[str]:
    """Returns the most recent run_id by started_at."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM runs ORDER BY started_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        return str(row[0]) if row else None


# ==============================================================================
# PRODUCT MANAGEMENT
# ==============================================================================

def get_or_create_product(
    conn,
    base_product_key: str,
    variant_key: str,
    display_name: str,
    brand: str = None,
    category: str = None
) -> int:
    """
    Gets existing product or creates new one. Returns product_id.
    Uses normalized keys for consistency.
    """
    norm_base = normalize_variant_key(base_product_key)
    norm_variant = normalize_variant_key(variant_key)
    
    if not norm_base or not norm_variant:
        raise ValueError(f"Invalid product keys after normalization: base={base_product_key}, variant={variant_key}")
    
    with conn.cursor() as cur:
        # Try to find by canonical variant_key
        cur.execute("SELECT id FROM products WHERE variant_key = %s", (norm_variant,))
        row = cur.fetchone()
        if row:
            return row[0]
        
        # Try to find by alias
        cur.execute("SELECT product_id FROM product_aliases WHERE alias_key = %s", (norm_variant,))
        row = cur.fetchone()
        if row:
            return row[0]
        
        # Create new product
        cur.execute("""
            INSERT INTO products (base_product_key, variant_key, display_name, brand, category)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (norm_base, norm_variant, display_name, brand, category))
        product_id = cur.fetchone()[0]
        
        print(f"📦 New product: {display_name} (id={product_id})")
        return product_id


def resolve_product(conn, variant_key: str) -> Optional[int]:
    """
    Resolves variant_key to product_id, checking both canonical key and aliases.
    Returns None if not found.
    """
    norm_key = normalize_variant_key(variant_key)
    if not norm_key:
        return None
    
    with conn.cursor() as cur:
        # Try canonical variant_key
        cur.execute("SELECT id FROM products WHERE variant_key = %s", (norm_key,))
        row = cur.fetchone()
        if row:
            return row[0]
        
        # Try alias
        cur.execute("SELECT product_id FROM product_aliases WHERE alias_key = %s", (norm_key,))
        row = cur.fetchone()
        if row:
            return row[0]
    
    return None


def add_product_alias(conn, product_id: int, alias_key: str):
    """Adds a normalized alias for a product."""
    norm_key = normalize_variant_key(alias_key)
    if not norm_key:
        print(f"⚠️ Skipping empty alias after normalization: {alias_key}")
        return
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO product_aliases (product_id, alias_key)
            VALUES (%s, %s)
            ON CONFLICT (alias_key) DO NOTHING
        """, (product_id, norm_key))


def update_product_prices(
    conn,
    product_id: int,
    reference_price: float = None,
    resale_estimate: float = None
):
    """Updates reference pricing for a product."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE products SET
                reference_price = COALESCE(%s, reference_price),
                resale_estimate = COALESCE(%s, resale_estimate),
                price_updated = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, (reference_price, resale_estimate, product_id))


# REMOVED: get_product_resale_estimate, get_product_resale_batch
# Reason: products.resale_estimate will remain NULL (no historical data available)
# Live-market pricing from active listings is the only truth source


# ==============================================================================
# LISTING MANAGEMENT
# ==============================================================================

def upsert_listing(
    conn,
    run_id: str,
    platform: str,
    source_id: str,
    url: str,
    title: str,
    product_id: int = None,
    image_url: str = None,
    buy_now_price: float = None,
    current_bid: float = None,
    bids_count: int = 0,
    end_time: datetime = None,
    location: str = None,
    shipping_cost: float = None,
    pickup_available: bool = False,
    seller_rating: int = None
) -> int:
    """Upsert a listing record."""
    # Validate UUID at function entry
    run_id = assert_valid_uuid(run_id, context="upsert_listing()")
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO listings (
                run_id, platform, source_id, url, title, product_id, image_url,
                buy_now_price, current_bid, bids_count, end_time,
                location, shipping_cost, pickup_available, seller_rating,
                first_seen, last_seen
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                NOW(), NOW()
            )
            ON CONFLICT (platform, source_id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                url = EXCLUDED.url,
                title = EXCLUDED.title,
                product_id = COALESCE(EXCLUDED.product_id, listings.product_id),
                image_url = COALESCE(EXCLUDED.image_url, listings.image_url),
                buy_now_price = EXCLUDED.buy_now_price,
                current_bid = EXCLUDED.current_bid,
                bids_count = EXCLUDED.bids_count,
                end_time = EXCLUDED.end_time,
                location = COALESCE(EXCLUDED.location, listings.location),
                shipping_cost = COALESCE(EXCLUDED.shipping_cost, listings.shipping_cost),
                pickup_available = COALESCE(EXCLUDED.pickup_available, listings.pickup_available),
                seller_rating = COALESCE(EXCLUDED.seller_rating, listings.seller_rating),
                last_seen = NOW()
            RETURNING id
        """, (
            run_id, platform, source_id, url, title, product_id, image_url,
            buy_now_price, current_bid, bids_count, end_time,
            location, shipping_cost, pickup_available, seller_rating
        ))
        listing_id = cur.fetchone()[0]
    
    return listing_id


def get_listing_id(conn, platform: str, source_id: str) -> Optional[int]:
    """Gets listing_id by platform and source_id."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM listings WHERE platform = %s AND source_id = %s
        """, (platform, source_id))
        row = cur.fetchone()
        return row[0] if row else None


def update_listing_details(conn, listing_id: int, **details):
    """
    Updates listing with additional details (from detail page scraping).
    Accepts: seller_rating, shipping_cost, pickup_available, location
    """
    if not details:
        return
    
    updates = []
    values = []
    
    for field, value in details.items():
        if value is not None and field in ('seller_rating', 'shipping_cost', 'pickup_available', 'location'):
            updates.append(f"{field} = %s")
            values.append(value)
    
    if not updates:
        return
    
    values.append(listing_id)
    
    with conn.cursor() as cur:
        cur.execute(f"""
            UPDATE listings SET {', '.join(updates)}, last_seen = NOW()
            WHERE id = %s
        """, values)


def update_listing_variant_key(conn, listing_id: int, variant_key: str):
    """
    Updates listing with variant_key for market pricing grouping.
    
    CRITICAL: This enables live auction pricing by allowing market_prices
    to group listings by variant_key and calculate resale from actual bids.
    
    Args:
        conn: Database connection
        listing_id: Listing ID to update
        variant_key: Product variant identifier (e.g., 'apple_iphone_12_mini_128gb')
    """
    if not variant_key:
        return
    
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE listings 
            SET variant_key = %s, last_seen = NOW()
            WHERE id = %s
        """, (variant_key, listing_id))


# ==============================================================================
# DEAL MANAGEMENT (Single Products)
# ==============================================================================

def insert_deal(
    conn,
    listing_id: int,
    product_id: int,
    run_id: str,
    cost_estimate: float,
    market_value: float,
    expected_profit: float,
    deal_score: float,
    strategy: str,
    strategy_reason: str = None
) -> int:
    """
    Inserts a deal evaluation for a single product. Returns deal_id.
    Uses (listing_id, run_id) as unique key - one evaluation per listing per run.
    """
    # Validate strategy
    valid_strategies = {'buy_now', 'bid_now', 'watch', 'skip'}
    if strategy not in valid_strategies:
        strategy = 'skip'
    
    # Clamp deal_score to 1.0-10.0
    deal_score = max(1.0, min(10.0, float(deal_score)))
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO deals (
                listing_id, product_id, run_id,
                cost_estimate, market_value, expected_profit,
                deal_score, strategy, strategy_reason, evaluated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (listing_id, run_id) DO UPDATE SET
                product_id = EXCLUDED.product_id,
                cost_estimate = EXCLUDED.cost_estimate,
                market_value = EXCLUDED.market_value,
                expected_profit = EXCLUDED.expected_profit,
                deal_score = EXCLUDED.deal_score,
                strategy = EXCLUDED.strategy,
                strategy_reason = EXCLUDED.strategy_reason,
                evaluated_at = NOW()
            RETURNING id
        """, (
            listing_id, product_id, run_id,
            cost_estimate, market_value, expected_profit,
            deal_score, strategy, strategy_reason
        ))
        deal_id = cur.fetchone()[0]
    
    return deal_id


def insert_deal_audit(
    conn,
    deal_id: int,
    price_source: str,
    ai_cost_usd: float = None,
    cache_hit: bool = False,
    web_search_used: bool = False,
    vision_used: bool = False
):
    """Inserts pipeline metadata for a deal."""
    valid_sources = {
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    }
    if price_source not in valid_sources:
        price_source = 'no_price'
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO deal_audit (deal_id, price_source, ai_cost_usd, cache_hit, web_search_used, vision_used)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (deal_id) DO UPDATE SET
                price_source = EXCLUDED.price_source,
                ai_cost_usd = EXCLUDED.ai_cost_usd,
                cache_hit = EXCLUDED.cache_hit,
                web_search_used = EXCLUDED.web_search_used,
                vision_used = EXCLUDED.vision_used,
                created_at = NOW()
        """, (deal_id, price_source, ai_cost_usd, cache_hit, web_search_used, vision_used))


# ==============================================================================
# BUNDLE MANAGEMENT
# ==============================================================================

def insert_bundle(
    conn,
    listing_id: int,
    run_id: str,
    total_cost: float,
    total_value: float,
    expected_profit: float,
    deal_score: float = None,
    strategy: str = None,
    strategy_reason: str = None
) -> int:
    """
    Inserts a bundle evaluation. Returns bundle_id.
    Uses (listing_id, run_id) as unique key.
    """
    valid_strategies = {'buy_now', 'bid_now', 'watch', 'skip', None}
    if strategy not in valid_strategies:
        strategy = 'skip'
    
    if deal_score is not None:
        deal_score = max(1.0, min(10.0, float(deal_score)))
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bundles (
                listing_id, run_id,
                total_cost, total_value, expected_profit,
                deal_score, strategy, strategy_reason, evaluated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (listing_id, run_id) DO UPDATE SET
                total_cost = EXCLUDED.total_cost,
                total_value = EXCLUDED.total_value,
                expected_profit = EXCLUDED.expected_profit,
                deal_score = EXCLUDED.deal_score,
                strategy = EXCLUDED.strategy,
                strategy_reason = EXCLUDED.strategy_reason,
                evaluated_at = NOW()
            RETURNING id
        """, (
            listing_id, run_id,
            total_cost, total_value, expected_profit,
            deal_score, strategy, strategy_reason
        ))
        bundle_id = cur.fetchone()[0]
    
    return bundle_id


def insert_bundle_item(
    conn,
    bundle_id: int,
    product_name: str,
    quantity: int = 1,
    product_id: int = None,
    unit_value: float = None
) -> int:
    """Inserts a bundle component. Returns bundle_item_id."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bundle_items (bundle_id, product_id, product_name, quantity, unit_value)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (bundle_id, product_id, product_name, max(1, quantity), unit_value))
        return cur.fetchone()[0]


def insert_bundle_audit(
    conn,
    bundle_id: int,
    price_source: str,
    ai_cost_usd: float = None,
    cache_hit: bool = False,
    web_search_used: bool = False
):
    """Inserts pipeline metadata for a bundle."""
    valid_sources = {
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    }
    if price_source not in valid_sources:
        price_source = 'bundle_aggregate'
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bundle_audit (bundle_id, price_source, ai_cost_usd, cache_hit, web_search_used)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (bundle_id) DO UPDATE SET
                price_source = EXCLUDED.price_source,
                ai_cost_usd = EXCLUDED.ai_cost_usd,
                cache_hit = EXCLUDED.cache_hit,
                web_search_used = EXCLUDED.web_search_used,
                created_at = NOW()
        """, (bundle_id, price_source, ai_cost_usd, cache_hit, web_search_used))


# ==============================================================================
# USER ACTIONS
# ==============================================================================

def set_user_action(
    conn,
    listing_id: int,
    action: str,
    notes: str = None,
    tags: List[str] = None
):
    """Sets or updates user action for a listing (UPSERT)."""
    valid_actions = {'buy', 'watch', 'ignore', 'purchased', 'archived'}
    if action not in valid_actions:
        raise ValueError(f"Invalid action: {action}. Must be one of: {valid_actions}")
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_actions (listing_id, action, notes, tags, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (listing_id) DO UPDATE SET
                action = EXCLUDED.action,
                notes = EXCLUDED.notes,
                tags = EXCLUDED.tags,
                updated_at = NOW()
        """, (listing_id, action, notes, tags))


def get_user_action(conn, listing_id: int) -> Optional[Dict]:
    """Gets user action for a listing."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT action, notes, tags, created_at, updated_at
            FROM user_actions WHERE listing_id = %s
        """, (listing_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            'action': row[0],
            'notes': row[1],
            'tags': row[2],
            'created_at': row[3],
            'updated_at': row[4]
        }


# ==============================================================================
# PRICE CACHE
# ==============================================================================

def get_cached_price(conn, variant_key: str) -> Optional[Dict]:
    """Gets cached price data for a variant if not expired."""
    norm_key = normalize_variant_key(variant_key)
    if not norm_key:
        return None
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT new_price, resale_price, source_urls, sample_size, cached_at
            FROM price_cache
            WHERE variant_key = %s AND expires_at > NOW()
        """, (norm_key,))
        row = cur.fetchone()
        if not row:
            return None
        
        return {
            'new_price': float(row[0]) if row[0] else None,
            'resale_price': float(row[1]) if row[1] else None,
            'source_urls': row[2],
            'sample_size': row[3],
            'cached_at': row[4]
        }


def set_cached_price(
    conn,
    variant_key: str,
    new_price: float = None,
    resale_price: float = None,
    source_urls: List[str] = None,
    sample_size: int = 1,
    cache_hours: int = 24
):
    """Caches price data for a variant."""
    norm_key = normalize_variant_key(variant_key)
    if not norm_key:
        return
    
    expires = datetime.now() + timedelta(hours=cache_hours)
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO price_cache (variant_key, new_price, resale_price, source_urls, sample_size, cached_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (variant_key) DO UPDATE SET
                new_price = EXCLUDED.new_price,
                resale_price = EXCLUDED.resale_price,
                source_urls = EXCLUDED.source_urls,
                sample_size = EXCLUDED.sample_size,
                cached_at = NOW(),
                expires_at = EXCLUDED.expires_at
        """, (norm_key, new_price, resale_price, json.dumps(source_urls) if source_urls else None, sample_size, expires))
    
    print(f"💾 Cached price: {norm_key} = {resale_price} CHF (n={sample_size})")


def clean_price_cache(conn) -> int:
    """Removes expired price cache entries. Returns count deleted."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM price_cache WHERE expires_at < NOW()")
        deleted = cur.rowcount
        if deleted > 0:
            print(f"🧹 Cleaned {deleted} expired price cache entries")
        return deleted


# ==============================================================================
# PRICE HISTORY (DISABLED - No access to ended auctions)
# ==============================================================================
# NOTE: Ricardo only exposes ACTIVE listings, not ended auctions.
# Therefore, price_history table will remain empty and historical learning is not possible.
# Live-market-first pricing is the only viable approach.


# ==============================================================================
# QUERY HELPERS (Using Views)
# ==============================================================================

def get_latest_deals(conn, min_profit: float = None, limit: int = 100) -> List[Dict]:
    """Gets deals from the latest run using v_latest_deals view."""
    conditions = []
    params = []
    
    if min_profit is not None:
        conditions.append("expected_profit >= %s")
        params.append(min_profit)
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT * FROM v_latest_deals
            {where_clause}
            ORDER BY deal_score DESC, expected_profit DESC
            LIMIT %s
        """, params)
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_latest_bundles(conn, limit: int = 50) -> List[Dict]:
    """Gets bundles from the latest run using v_latest_bundles view."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM v_latest_bundles
            ORDER BY deal_score DESC NULLS LAST, expected_profit DESC
            LIMIT %s
        """, (limit,))
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_dashboard(conn, limit: int = 50) -> List[Dict]:
    """Gets combined deals + bundles using v_dashboard view."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM v_dashboard
            LIMIT %s
        """, (limit,))
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_action_required(conn, limit: int = 50) -> List[Dict]:
    """Gets items requiring action using v_action_required view."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM v_action_required
            LIMIT %s
        """, (limit,))
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_watchlist(conn) -> List[Dict]:
    """Gets user's watchlist using v_watchlist view."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM v_watchlist")
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_purchased(conn) -> List[Dict]:
    """Gets purchased items using v_purchased view."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM v_purchased")
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_deals_for_product_family(conn, base_product_key: str) -> List[Dict]:
    """Gets all deals for a product family (e.g., all iPhone 12 mini variants)."""
    norm_key = normalize_variant_key(base_product_key)
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM v_latest_deals
            WHERE base_product_key = %s
            ORDER BY expected_profit DESC
        """, (norm_key,))
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


# ==============================================================================
# RUN STATISTICS
# ==============================================================================

def get_run_stats(conn, run_id: str = None) -> Dict:
    """Gets statistics for a run (or latest run if not specified)."""
    if not run_id:
        run_id = get_latest_run_id(conn)
    
    if not run_id:
        return {}
    
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                id, mode, status, started_at, finished_at, duration_sec,
                listings_found, deals_created, bundles_created, profitable_deals,
                ai_cost_usd, websearch_calls, error_message
            FROM runs WHERE id = %s
        """, (run_id,))
        
        row = cur.fetchone()
        if not row:
            return {}
        
        return {
            'run_id': str(row[0]),
            'mode': row[1],
            'status': row[2],
            'started_at': row[3],
            'finished_at': row[4],
            'duration_sec': row[5],
            'listings_found': row[6],
            'deals_created': row[7],
            'bundles_created': row[8],
            'profitable_deals': row[9],
            'ai_cost_usd': float(row[10]) if row[10] else 0,
            'websearch_calls': row[11],
            'error_message': row[12]
        }


# ==============================================================================
# CLEANUP
# ==============================================================================

def clear_run_data(conn, run_id: str):
    """Clears all data for a specific run (deals, bundles, listings)."""
    with conn.cursor() as cur:
        # Deals and bundles cascade from listings
        cur.execute("DELETE FROM deals WHERE run_id = %s", (run_id,))
        deals_deleted = cur.rowcount
        
        cur.execute("DELETE FROM bundles WHERE run_id = %s", (run_id,))
        bundles_deleted = cur.rowcount
        
        # Don't delete listings - they persist across runs
        # Only update last_seen
        
        print(f"🧹 Cleared run {run_id[:8]}...: {deals_deleted} deals, {bundles_deleted} bundles")


def clear_listings(conn, run_id: str = None):
    """
    Clears listings. If run_id provided, only clears that run's associated data.
    For testing, clears all data.
    """
    with conn.cursor() as cur:
        if run_id:
            # Clear deals and bundles for this run
            cur.execute("DELETE FROM deals WHERE run_id = %s", (run_id,))
            cur.execute("DELETE FROM bundles WHERE run_id = %s", (run_id,))
            print(f"🧹 Cleared run data: {run_id[:8]}...")
        else:
            # Clear everything (for testing)
            cur.execute("DELETE FROM deals")
            cur.execute("DELETE FROM bundles")
            cur.execute("DELETE FROM listings")
            cur.execute("DELETE FROM price_history")
            cur.execute("DELETE FROM price_cache")
            cur.execute("DELETE FROM user_actions")
            print("🧹 Cleared all data (testing mode)")


def cleanup_old_listings(conn, days: int = 30):
    """Deletes listings older than X days (and their deals/bundles via CASCADE)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    with conn.cursor() as cur:
        cur.execute("DELETE FROM listings WHERE last_seen < %s", (cutoff,))
        deleted = cur.rowcount
        
        if deleted > 0:
            print(f"🧹 Deleted {deleted} old listings (>{days} days)")
        else:
            print("🧹 No old listings to delete")


# ==============================================================================
# EXPORT
# ==============================================================================

def export_deals_json(conn, filepath: str = "last_run_deals.json"):
    """Exports latest deals to JSON file."""
    deals = get_latest_deals(conn, limit=10000)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"📁 Exported {len(deals)} deals to {filepath}")
    return len(deals)


def export_deals_csv(conn, filepath: str = "last_run_deals.csv"):
    """Exports latest deals to CSV file."""
    import csv
    
    deals = get_latest_deals(conn, limit=10000)
    
    if not deals:
        print("⚠️ No deals to export")
        return 0
    
    fieldnames = list(deals[0].keys())
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deals)
    
    print(f"📁 Exported {len(deals)} deals to {filepath}")
    return len(deals)


def export_bundles_json(conn, filepath: str = "last_run_bundles.json"):
    """Exports latest bundles to JSON file with full component details."""
    bundles = get_latest_bundles(conn, limit=10000)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            'export_time': datetime.now().isoformat(),
            'total_bundles': len(bundles),
            'bundles': bundles
        }, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"📁 Exported {len(bundles)} bundles to {filepath}")
    return len(bundles)


def export_bundles_csv(conn, filepath: str = "last_run_bundles.csv"):
    """Exports latest bundles to CSV file."""
    import csv
    
    bundles = get_latest_bundles(conn, limit=10000)
    
    if not bundles:
        print("⚠️ No bundles to export")
        return 0
    
    fieldnames = list(bundles[0].keys())
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(bundles)
    
    print(f"📁 Exported {len(bundles)} bundles to {filepath}")
    return len(bundles)


def export_products_json(conn, filepath: str = "last_run_products.json"):
    """Exports all products from latest run."""
    with conn.cursor() as cur:
        # Get products that were part of the latest run
        cur.execute("""
            SELECT DISTINCT
                p.id,
                p.base_product_key,
                p.variant_key,
                p.display_name,
                p.brand,
                p.category,
                p.created_at,
                p.updated_at
            FROM products p
            JOIN deals d ON d.product_id = p.id
            WHERE d.run_id = (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1)
            ORDER BY p.display_name
        """)
        
        columns = [desc[0] for desc in cur.description]
        products = [dict(zip(columns, row)) for row in cur.fetchall()]
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            'export_time': datetime.now().isoformat(),
            'total_products': len(products),
            'products': products
        }, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"📁 Exported {len(products)} products to {filepath}")
    return len(products)


def export_run_stats(conn, filepath: str = "last_run_stats.json"):
    """Exports comprehensive run statistics and metadata."""
    cur = conn.cursor()
    try:
        # Get latest run metadata
        cur.execute("""
            SELECT 
                id,
                started_at,
                finished_at,
                status,
                mode,
                listings_found,
                deals_created,
                bundles_created,
                profitable_deals,
                ai_cost_usd,
                websearch_calls,
                duration_sec,
                error_message
            FROM runs
            ORDER BY started_at DESC
            LIMIT 1
        """)
        
        run_row = cur.fetchone()
        if not run_row:
            print("⚠️ No run data found")
            return 0
        
        columns = [desc[0] for desc in cur.description]
        
        # Debug: Check if we have matching lengths
        if len(columns) != len(run_row):
            print(f"⚠️ Column/row mismatch: {len(columns)} columns vs {len(run_row)} values")
            print(f"Columns: {columns}")
            print(f"Row length: {len(run_row)}")
            return 0
        
        run_data = dict(zip(columns, run_row))
        
        # Ensure we have an id field
        if 'id' not in run_data:
            print(f"⚠️ No 'id' field in run_data. Available fields: {list(run_data.keys())}")
            return 0
        
        # Debug: Print run_data to see what we have
        print(f"🔍 DEBUG: run_data keys: {list(run_data.keys())}")
        print(f"🔍 DEBUG: run_data['id'] type: {type(run_data['id'])}")
        print(f"🔍 DEBUG: run_data['id'] value: {run_data['id']}")
        
        # Extract run_id safely - keep as string for psycopg2
        try:
            run_id = str(run_data['id'])
            print(f"🔍 DEBUG: run_id = {run_id} (type: {type(run_id)})")
        except Exception as e:
            print(f"❌ Error converting run_data['id'] to string: {e}")
            print(f"   run_data['id'] = {run_data['id']}")
            print(f"   type = {type(run_data['id'])}")
            return 0
        
        # Get deal statistics
        print("🔍 DEBUG: Executing deal statistics query...")
        print(f"🔍 DEBUG: run_id parameter = {run_id} (type: {type(run_id)})")
        try:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_deals,
                    COUNT(*) FILTER (WHERE expected_profit > 20) as profitable_deals,
                    COUNT(*) FILTER (WHERE expected_profit > 50) as very_profitable_deals,
                    ROUND(AVG(expected_profit)::numeric, 2) as avg_profit,
                    ROUND(MAX(expected_profit)::numeric, 2) as max_profit,
                    ROUND(MIN(expected_profit)::numeric, 2) as min_profit
                FROM deals
                WHERE run_id = %s
            """, (run_id,))
            print("🔍 DEBUG: Query executed successfully")
        except Exception as e:
            print(f"❌ SQL execution failed: {e}")
            print(f"   Error type: {type(e)}")
            import traceback
            traceback.print_exc()
            return 0
        
        print("🔍 DEBUG: Fetching deal row...")
        deal_row = cur.fetchone()
        print(f"🔍 DEBUG: deal_row = {deal_row}")
        if deal_row:
            print(f"🔍 DEBUG: Creating deal_stats dict from {len(deal_row)} values...")
            deal_stats = dict(zip([desc[0] for desc in cur.description], deal_row))
            print("🔍 DEBUG: deal_stats created successfully")
        else:
            deal_stats = {
                'total_deals': 0,
                'profitable_deals': 0,
                'very_profitable_deals': 0,
                'avg_profit': 0,
                'max_profit': 0,
                'min_profit': 0
            }
        
        # Get bundle statistics
        cur.execute("""
            SELECT 
                COUNT(*) as total_bundles,
                COUNT(*) FILTER (WHERE expected_profit > 20) as profitable_bundles,
                ROUND(AVG(expected_profit)::numeric, 2) as avg_bundle_profit
            FROM bundles
            WHERE run_id = %s
        """, (run_id,))
        
        bundle_row = cur.fetchone()
        if bundle_row:
            bundle_stats = dict(zip([desc[0] for desc in cur.description], bundle_row))
        else:
            bundle_stats = {
                'total_bundles': 0,
                'profitable_bundles': 0,
                'avg_bundle_profit': 0
            }
        
        # Get strategy breakdown
        cur.execute("""
            SELECT 
                strategy,
                COUNT(*) as count
            FROM deals
            WHERE run_id = %s
            GROUP BY strategy
            ORDER BY count DESC
        """, (run_id,))
        
        print("🔍 DEBUG: Fetching strategies...")
        strategy_rows = cur.fetchall()
        print(f"🔍 DEBUG: Got {len(strategy_rows)} strategy rows")
        try:
            strategies = {row[0]: row[1] for row in strategy_rows} if strategy_rows else {}
            print(f"🔍 DEBUG: strategies dict created successfully")
        except Exception as e:
            print(f"❌ Error creating strategies dict: {e}")
            print(f"   Rows: {strategy_rows}")
            strategies = {}
        
        stats = {
            'export_time': datetime.now().isoformat(),
            'run_metadata': run_data,
            'deal_statistics': deal_stats,
            'bundle_statistics': bundle_stats,
            'strategy_breakdown': strategies
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"📁 Exported run statistics to {filepath}")
        return 1
    finally:
        cur.close()


# ==============================================================================
# BRIDGE FUNCTION: Old format → New schema
# ==============================================================================

def save_evaluation(conn, data: Dict[str, Any]) -> Dict[str, int]:
    """
    Bridge function: Takes old upsert_listing data format and inserts into new v2.2 schema.
    
    This handles the full flow:
    1. Get/create product (from variant_key)
    2. Upsert listing
    3. Insert deal OR bundle
    4. Insert audit record
    
    Args:
        conn: Database connection
        data: Old format dict with all fields from main.py
        
    Returns:
        Dict with created IDs: {listing_id, product_id, deal_id/bundle_id}
    """
    import json
    
    # Extract run_id (required)
    run_id = data.get("run_id")
    if not run_id:
        raise ValueError("run_id is required")
    
    # ✅ FAIL FAST: Validate UUID before any expensive operations
    run_id = assert_valid_uuid(run_id, context="save_evaluation()")
    
    # Extract source listing info
    platform = data.get("platform", "ricardo")
    source_id = data.get("listing_id") or data.get("source_listing_id")
    if not source_id:
        raise ValueError("listing_id or source_listing_id is required")
    
    url = data.get("url", "")
    title = data.get("title", "")
    
    # ---------------------------------------------------------------------------
    # 1. Get or create product
    # ---------------------------------------------------------------------------
    product_id = None
    variant_key = data.get("variant_key")
    
    if variant_key:
        # Try to resolve existing product
        product_id = resolve_product(conn, variant_key)
        
        if not product_id:
            # Create new product
            # Generate base_product_key by removing storage/color specifics
            base_key = variant_key.split("_")[0:3]  # e.g., "apple_iphone_12" from "apple_iphone_12_128gb_green"
            base_product_key = "_".join(base_key) if len(base_key) >= 2 else variant_key
            
            display_name = data.get("cleaned_title") or data.get("title") or variant_key
            
            product_id = get_or_create_product(
                conn,
                base_product_key=base_product_key,
                variant_key=variant_key,
                display_name=display_name,
                brand=None,  # Could extract from variant_key
                category=None
            )
    
    # ---------------------------------------------------------------------------
    # 2. Upsert listing
    # ---------------------------------------------------------------------------
    listing_id = upsert_listing(
        conn,
        run_id=run_id,
        platform=platform,
        source_id=source_id,
        url=url,
        title=title,
        product_id=product_id,
        image_url=data.get("image_url"),
        buy_now_price=data.get("buy_now_price"),
        current_bid=data.get("current_price_ricardo"),
        bids_count=data.get("bids_count", 0),
        end_time=data.get("end_time"),
        location=data.get("location"),
        shipping_cost=data.get("shipping_cost"),
        pickup_available=data.get("pickup_available", False),
        seller_rating=data.get("seller_rating")
    )
    
    # ---------------------------------------------------------------------------
    # 3. Insert deal OR bundle
    # ---------------------------------------------------------------------------
    is_bundle = data.get("is_bundle", False)
    
    # Calculate cost estimate (what you'd pay)
    buy_now = data.get("buy_now_price")
    predicted = data.get("predicted_final_price")
    current = data.get("current_price_ricardo")
    cost_estimate = buy_now or predicted or current or 0
    
    # Market value (what you'd sell for)
    market_value = data.get("resale_price_est") or data.get("market_value") or 0
    
    # Expected profit
    expected_profit = data.get("expected_profit") or (market_value - cost_estimate if market_value and cost_estimate else 0)
    
    # Deal score (clamp to 1-10)
    deal_score = data.get("deal_score") or 5.0
    deal_score = max(1.0, min(10.0, float(deal_score)))
    
    # Strategy
    strategy = data.get("recommended_strategy", "skip")
    valid_strategies = {'buy_now', 'bid_now', 'watch', 'skip'}
    if strategy not in valid_strategies:
        # Map old strategies to new
        strategy_map = {'bid': 'bid_now', 'buy': 'buy_now'}
        strategy = strategy_map.get(strategy, 'skip')
    
    strategy_reason = data.get("strategy_reason")
    
    # Price source for audit
    price_source = data.get("price_source", "no_price")
    
    result = {
        'listing_id': listing_id,
        'product_id': product_id,
    }
    
    if is_bundle:
        # ---------------------------------------------------------------------------
        # 3a. Insert bundle
        # ---------------------------------------------------------------------------
        bundle_cost = cost_estimate
        bundle_value = data.get("resale_price_bundle") or market_value
        bundle_profit = expected_profit
        
        bundle_id = insert_bundle(
            conn,
            listing_id=listing_id,
            run_id=run_id,
            total_cost=bundle_cost,
            total_value=bundle_value,
            expected_profit=bundle_profit,
            deal_score=deal_score,
            strategy=strategy,
            strategy_reason=strategy_reason
        )
        
        result['bundle_id'] = bundle_id
        
        # Insert bundle items if components provided
        bundle_components = data.get("bundle_components")
        if bundle_components:
            if isinstance(bundle_components, str):
                try:
                    bundle_components = json.loads(bundle_components)
                except:
                    bundle_components = []
            
            if isinstance(bundle_components, list):
                for comp in bundle_components:
                    if isinstance(comp, dict):
                        insert_bundle_item(
                            conn,
                            bundle_id=bundle_id,
                            product_name=comp.get("name", "Unknown"),
                            quantity=comp.get("quantity", 1),
                            unit_value=comp.get("value")
                        )
                    elif isinstance(comp, str):
                        insert_bundle_item(
                            conn,
                            bundle_id=bundle_id,
                            product_name=comp,
                            quantity=1
                        )
        
        # Insert bundle audit
        insert_bundle_audit(
            conn,
            bundle_id=bundle_id,
            price_source=price_source,
            ai_cost_usd=data.get("ai_cost_usd"),
            cache_hit=data.get("cache_hit", False),
            web_search_used=data.get("web_search_used", False)
        )
        
    else:
        # ---------------------------------------------------------------------------
        # 3b. Insert deal (single product)
        # ---------------------------------------------------------------------------
        deal_id = insert_deal(
            conn,
            listing_id=listing_id,
            product_id=product_id,
            run_id=run_id,
            cost_estimate=cost_estimate,
            market_value=market_value,
            expected_profit=expected_profit,
            deal_score=deal_score,
            strategy=strategy,
            strategy_reason=strategy_reason
        )
        
        result['deal_id'] = deal_id
        
        # Insert deal audit
        insert_deal_audit(
            conn,
            deal_id=deal_id,
            price_source=price_source,
            ai_cost_usd=data.get("ai_cost_usd"),
            cache_hit=data.get("cache_hit", False),
            web_search_used=data.get("web_search_used", False),
            vision_used=data.get("vision_used", False)
        )
    
    # ---------------------------------------------------------------------------
    # 4. Record price history if applicable
    # ---------------------------------------------------------------------------
    # NOTE: Historical price tracking removed (price_history out of scope)
    # Ricardo only exposes active listings, not ended auctions
    
    # Print save confirmation
    strategy_icon = {
        'buy_now': '🔥',
        'bid_now': '🔥',
        'watch': '👀',
        'skip': '⏭️',
    }.get(strategy, '💾')
    
    type_label = "Bundle" if is_bundle else "Deal"
    print(f"{strategy_icon} Saved {type_label}: {title[:50]}...")
    
    return result


# Alias for backward compatibility
def upsert_listing_legacy(conn, data: Dict[str, Any]):
    """
    DEPRECATED: Use save_evaluation() instead.
    This is a drop-in replacement for the old upsert_listing() function.
    """
    save_evaluation(conn, data)


# ==============================================================================
# BACKWARD COMPATIBILITY ALIASES
# ==============================================================================

# These map old function names to new ones for easier migration

def get_listings(conn, run_id: str = None, min_score: float = None, strategy: str = None, limit: int = 100) -> List[Dict]:
    """Backward compatibility: Use get_latest_deals() instead."""
    return get_latest_deals(conn, min_profit=None, limit=limit)


def get_bundle_groups(conn, run_id: str = None, limit: int = 50) -> List[Dict]:
    """Backward compatibility: Use get_latest_bundles() instead."""
    return get_latest_bundles(conn, limit=limit)


def export_listings_json(conn, run_id: str = None, filepath: str = "last_run_listings.json"):
    """Backward compatibility: Use export_deals_json() instead."""
    return export_deals_json(conn, filepath)


def export_listings_csv(conn, run_id: str = None, filepath: str = "last_run_listings.csv"):
    """Backward compatibility: Use export_deals_csv() instead."""
    return export_deals_csv(conn, filepath)


# Legacy market data functions - now use price_cache
def get_cached_market_data(conn, variant_key: str) -> Optional[Dict]:
    """Backward compatibility: Use get_cached_price() instead."""
    return get_cached_price(conn, variant_key)


def set_cached_market_data(conn, variant_key: str, market_value: float, resale_price: float, 
                           sample_size: int, confidence: float, source: str, 
                           buy_now_ceiling: float = None, cache_days: int = 7):
    """Backward compatibility: Use set_cached_price() instead."""
    set_cached_price(conn, variant_key, new_price=market_value, resale_price=resale_price, 
                     sample_size=sample_size, cache_hours=cache_days * 24)


def clear_expired_market_data(conn):
    """Backward compatibility: Use clean_price_cache() instead."""
    return clean_price_cache(conn)
