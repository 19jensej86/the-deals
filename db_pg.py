"""
Database Manager - v7.0 (Detail Scraping)
=========================================
Changes from v6.2:
- NEW: seller_rating column (INT) - Seller trustworthiness %
- NEW: shipping_cost column (NUMERIC) - Shipping cost in CHF
- NEW: pickup_available column (BOOLEAN) - Can pickup in person
- NEW: update_listing_details() - Updates listing with detail page data

Changes from v6.1:
- NEW: clear_stale_market_for_variant() - Clears old market data before fresh calculation

Note: end_time is NULL for Sofortkauf-only listings (expected behavior).

PostgreSQL database operations with:
- Auto-migration for missing columns
- Clear on start option (for testing)
- Bundle fields support
- Price history tracking
- Recommended strategy storage
- Market data caching (v6.0)
- Stale data clearing (v6.2)
- Detail page data (v7.0)
"""

import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import json


# ==============================================================================
# SCHEMA DEFINITION
# ==============================================================================

# All columns that should exist in the listings table
# Format: (column_name, column_type, default_value_or_None)
# v7.3.5: OPTIMIZED COLUMN ORDER - Logically grouped for SELECT * readability
LISTINGS_COLUMNS = [
    # ========================================================================
    # GROUP 1: IDENTIFICATION (Most important for joins/lookups)
    # ========================================================================
    ("id", "SERIAL PRIMARY KEY", None),
    ("platform", "TEXT NOT NULL", None),
    ("listing_id", "TEXT NOT NULL", None),
    ("title", "TEXT", None),
    ("variant_key", "TEXT", None),
    
    # ========================================================================
    # GROUP 2: PRICES & PROFIT (Most important for analysis!)
    # ========================================================================
    ("buy_now_price", "NUMERIC", None),
    ("current_price_ricardo", "NUMERIC", None),
    ("predicted_final_price", "NUMERIC", None),
    ("new_price", "NUMERIC", None),
    ("resale_price_est", "NUMERIC", None),
    ("resale_price_bundle", "NUMERIC", None),
    ("expected_profit", "NUMERIC", None),
    ("market_value", "NUMERIC", None),
    ("buy_now_ceiling", "NUMERIC", None),
    ("shipping_cost", "NUMERIC", None),
    ("price_source", "TEXT", None),
    
    # ========================================================================
    # GROUP 3: DEAL EVALUATION
    # ========================================================================
    ("deal_score", "NUMERIC", None),
    ("recommended_strategy", "TEXT", None),
    ("strategy_reason", "TEXT", None),
    ("market_based_resale", "BOOLEAN", "FALSE"),
    ("market_sample_size", "INTEGER", None),
    
    # ========================================================================
    # GROUP 4: BUNDLE INFO
    # ========================================================================
    ("is_bundle", "BOOLEAN", "FALSE"),
    ("bundle_components", "JSONB", None),
    
    # ========================================================================
    # GROUP 5: AUCTION INFO
    # ========================================================================
    ("bids_count", "INTEGER", None),
    ("hours_remaining", "FLOAT", None),
    ("end_time", "TIMESTAMP", None),
    
    # ========================================================================
    # GROUP 6: LOCATION & TRANSPORT
    # ========================================================================
    ("location", "TEXT", None),
    ("postal_code", "TEXT", None),
    ("shipping", "TEXT", None),
    ("transport_car", "BOOLEAN", None),
    ("pickup_available", "BOOLEAN", None),
    ("seller_rating", "INTEGER", None),
    
    # ========================================================================
    # GROUP 7: METADATA (v7.3.5 NEW)
    # ========================================================================
    ("run_id", "TEXT", None),                # NEW: Which run created this?
    ("web_search_used", "BOOLEAN", None),    # NEW: Was web search used?
    ("cache_hit", "BOOLEAN", None),          # NEW: Was it a cache hit?
    ("ai_cost_usd", "NUMERIC", None),        # NEW: AI cost for this listing
    ("vision_used", "BOOLEAN", None),        # NEW: Was vision/image analysis used?
    ("cleaned_title", "TEXT", None),         # NEW: Title after cleanup for search
    
    # ========================================================================
    # GROUP 8: TIMESTAMPS
    # ========================================================================
    ("created_at", "TIMESTAMP", "NOW()"),
    ("updated_at", "TIMESTAMP", "NOW()"),
    
    # ========================================================================
    # GROUP 9: LONG TEXT & URLs (Last for SELECT * readability)
    # ========================================================================
    ("description", "TEXT", None),
    ("ai_notes", "TEXT", None),
    ("image_url", "TEXT", None),
    ("url", "TEXT", None),
]

# Columns to skip when checking (they are part of constraints, not addable)
SKIP_COLUMNS = ["id"]


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
# SCHEMA MANAGEMENT
# ==============================================================================

def get_existing_columns(conn, table_name: str) -> set:
    """Returns set of existing column names for a table"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s
        """, (table_name,))
        return {row[0] for row in cur.fetchall()}


def ensure_schema(conn):
    """
    Creates tables if not exist and adds missing columns.
    v7.3.5: Optimized column order + added run_id, web_search_used, cache_hit, ai_cost_usd.
    v7.0: Added seller_rating, shipping_cost, pickup_available columns.
    """
    with conn.cursor() as cur:
        # --------------------------------------------------------------------
        # 1. Create listings table if not exists
        # --------------------------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id SERIAL PRIMARY KEY,
                platform TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                title TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (platform, listing_id)
            );
        """)
        
        # --------------------------------------------------------------------
        # 2. Add missing columns (auto-migration)
        # --------------------------------------------------------------------
        existing = get_existing_columns(conn, "listings")
        
        for col_name, col_type, col_default in LISTINGS_COLUMNS:
            if col_name in SKIP_COLUMNS:
                continue
            if col_name in existing:
                continue
            
            # Build ALTER TABLE statement
            if col_default:
                alter_sql = f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {col_name} {col_type} DEFAULT {col_default}"
            else:
                # Extract base type (remove NOT NULL for ALTER)
                base_type = col_type.replace(" NOT NULL", "")
                alter_sql = f"ALTER TABLE listings ADD COLUMN IF NOT EXISTS {col_name} {base_type}"
            
            try:
                cur.execute(alter_sql)
                print(f"   ➕ Added column: {col_name} ({col_type})")
            except Exception as e:
                print(f"   ⚠️ Could not add {col_name}: {e}")
        
        # --------------------------------------------------------------------
        # 3. Create price_history table
        # --------------------------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                listing_id TEXT NOT NULL,
                price NUMERIC NOT NULL,
                bids_count INTEGER,
                observed_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # --------------------------------------------------------------------
        # 4. Create component_cache table (for bundle pricing)
        # --------------------------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS component_cache (
                id SERIAL PRIMARY KEY,
                component_name TEXT UNIQUE NOT NULL,
                median_price NUMERIC,
                sample_size INTEGER,
                price_range_low NUMERIC,
                price_range_high NUMERIC,
                last_search_query TEXT,
                cached_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP
            );
        """)
        
        # --------------------------------------------------------------------
        # 5. v6.0: Create market_data table
        # --------------------------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                id SERIAL PRIMARY KEY,
                variant_key TEXT UNIQUE NOT NULL,
                market_value NUMERIC,
                resale_price NUMERIC,
                sample_size INTEGER,
                confidence NUMERIC,
                source TEXT,
                buy_now_ceiling NUMERIC,
                calculated_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP
            );
        """)
        
        # --------------------------------------------------------------------
        # 6. Create indexes
        # --------------------------------------------------------------------
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_variant_key ON listings(variant_key);
            CREATE INDEX IF NOT EXISTS idx_listings_bundle ON listings(is_bundle);
            CREATE INDEX IF NOT EXISTS idx_listings_strategy ON listings(recommended_strategy);
            CREATE INDEX IF NOT EXISTS idx_listings_deal_score ON listings(deal_score DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_profit ON listings(expected_profit DESC);
            CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);
            CREATE INDEX IF NOT EXISTS idx_price_history_time ON price_history(observed_at);
            CREATE INDEX IF NOT EXISTS idx_component_cache_name ON component_cache(component_name);
            CREATE INDEX IF NOT EXISTS idx_market_data_variant ON market_data(variant_key);
            CREATE INDEX IF NOT EXISTS idx_listings_run_id ON listings(run_id);
            CREATE INDEX IF NOT EXISTS idx_listings_price_source ON listings(price_source);
            CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at DESC);
        """)
        
        conn.commit()
        print("✅ DB schema ready (v7.3.5 - optimized column order + new metadata fields)")


def clear_listings(conn):
    """
    Deletes ALL listings from the database.
    Use for testing to start fresh.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM listings")
        deleted = cur.rowcount
        
        # Also clear price history for deleted listings
        cur.execute("DELETE FROM price_history")
        
        # v6.2: Also clear market_data
        cur.execute("DELETE FROM market_data")
        
        conn.commit()
        print(f"🧹 Cleared {deleted} listings from database (testing mode)")
        return deleted


# ==============================================================================
# UPSERT
# ==============================================================================

def upsert_listing(conn, data: Dict[str, Any]):
    """
    Inserts or updates a listing.
    v7.3.5: Added run_id, web_search_used, cache_hit, ai_cost_usd fields.
    v7.0: Added seller_rating, shipping_cost, pickup_available fields.
    """
    fields = [
        "platform", "listing_id", "title", "description", "location", "postal_code",
        "shipping", "transport_car", "end_time", "image_url", "url",
        "ai_notes", "buy_now_price", "current_price_ricardo",
        "bids_count", "new_price", "resale_price_est", "expected_profit",
        "deal_score", "variant_key", "predicted_final_price",
        # v5.0 fields
        "is_bundle", "bundle_components", "resale_price_bundle",
        "recommended_strategy", "strategy_reason",
        "market_based_resale", "market_sample_size",
        # v6.0 fields
        "market_value", "price_source", "buy_now_ceiling", "hours_remaining",
        # v7.0 fields
        "seller_rating", "shipping_cost", "pickup_available",
        # v7.3.5 fields
        "run_id", "web_search_used", "cache_hit", "ai_cost_usd",
        # v9.0 fields
        "vision_used", "cleaned_title",
    ]

    # DEFENSIVE: Normalize ALL dict/list values to JSON strings before DB insert
    # psycopg2 cannot adapt dict/list types - must be serialized
    values = []
    for k in fields:
        v = data.get(k)
        # Convert any dict or list to JSON string (not just bundle_components)
        if v is not None and isinstance(v, (dict, list)):
            # OBSERVABILITY: Log dict/list normalization for debugging
            type_name = "dict" if isinstance(v, dict) else "list"
            print(f"   🗄️ DB normalize: field={k} ({type_name} → JSON)")
            v = json.dumps(v, ensure_ascii=False)
        values.append(v)
    
    placeholders = ", ".join(["%s"] * len(values))
    updates = ", ".join([f"{k}=EXCLUDED.{k}" for k in fields[2:]])  # skip platform+listing_id

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO listings ({', '.join(fields)})
            VALUES ({placeholders})
            ON CONFLICT (platform, listing_id)
            DO UPDATE SET {updates},
                          updated_at = NOW();
            """,
            values,
        )
    
    title = data.get('title', '')[:50]
    strategy = data.get('recommended_strategy', '')
    strategy_icon = {
        'buy_now': '🔥',
        'bid_now': '🔥',
        'bid': '💰',
        'watch': '👀',
        'skip': '⏭️',
    }.get(strategy, '💾')
    
    print(f"{strategy_icon} Saved: {title}...")


# ==============================================================================
# v7.0: UPDATE LISTING WITH DETAIL DATA
# ==============================================================================

def update_listing_details(conn, deal: Dict[str, Any]):
    """
    v7.0: Updates a listing with data from detail page scraping.
    
    Only updates fields that are not None in the deal dict.
    
    Args:
        conn: Database connection
        deal: Dict with listing_id and detail fields:
            - seller_rating
            - shipping_cost
            - pickup_available
            - description (full)
            - location
            - postal_code
            - shipping (method)
    """
    listing_id = deal.get("listing_id")
    if not listing_id:
        print("   ⚠️ No listing_id for detail update")
        return
    
    # Build dynamic UPDATE based on available data
    updates = []
    values = []
    
    # Fields to update from detail scraping
    detail_fields = [
        ("seller_rating", deal.get("seller_rating")),
        ("shipping_cost", deal.get("shipping_cost")),
        ("pickup_available", deal.get("pickup_available")),
        ("description", deal.get("description")),
        ("location", deal.get("location")),
        ("postal_code", deal.get("postal_code")),
        ("shipping", deal.get("shipping")),
    ]
    
    for field_name, field_value in detail_fields:
        if field_value is not None:
            updates.append(f"{field_name} = %s")
            values.append(field_value)
    
    if not updates:
        print(f"   ⚠️ No detail data to update for {listing_id}")
        return
    
    # Add listing_id for WHERE clause
    values.append(listing_id)
    
    update_sql = f"""
        UPDATE listings 
        SET {', '.join(updates)}, updated_at = NOW()
        WHERE listing_id = %s AND platform = 'ricardo'
    """
    
    with conn.cursor() as cur:
        cur.execute(update_sql, values)
        updated = cur.rowcount
    
    if updated > 0:
        title = deal.get("title", "")[:40]
        rating = deal.get("seller_rating")
        shipping = deal.get("shipping_cost")
        pickup = deal.get("pickup_available")
        print(f"   📝 Updated details: {title}... "
              f"(Rating={rating}%, Ship={shipping} CHF, Pickup={pickup})")
    else:
        print(f"   ⚠️ Listing {listing_id} not found for update")


def update_listing_reevaluation(conn, data: Dict[str, Any]):
    """
    OBJECTIVE A: Update listing with re-evaluated values after detail scraping.
    
    Updates profit, score, and strategy based on detail scraping results.
    This is called AFTER detail scraping to adjust deal metrics.
    
    Args:
        conn: Database connection
        data: Dict with:
            - listing_id (required)
            - expected_profit
            - deal_score
            - recommended_strategy
            - strategy_reason
    """
    listing_id = data.get("listing_id")
    if not listing_id:
        print("   ⚠️ No listing_id for re-evaluation update")
        return
    
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE listings
            SET expected_profit = %s,
                deal_score = %s,
                recommended_strategy = %s,
                strategy_reason = %s,
                updated_at = NOW()
            WHERE listing_id = %s AND platform = 'ricardo'
        """, (
            data.get("expected_profit"),
            data.get("deal_score"),
            data.get("recommended_strategy"),
            data.get("strategy_reason"),
            listing_id
        ))
        updated = cur.rowcount
    
    if updated > 0:
        print(f"   ✅ Re-evaluated: {listing_id}")
    else:
        print(f"   ⚠️ Listing {listing_id} not found for re-evaluation")


# ==============================================================================
# v6.2: STALE DATA MANAGEMENT
# ==============================================================================

def clear_stale_market_for_variant(conn, variant_key: str):
    """
    v6.2: Clears stale market data for a variant before fresh calculation.
    """
    if not variant_key:
        return
    
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM market_data WHERE variant_key = %s
        """, (variant_key,))
        
        cur.execute("""
            UPDATE listings 
            SET market_value = NULL,
                buy_now_ceiling = NULL,
                market_sample_size = NULL,
                price_source = NULL
            WHERE variant_key = %s
        """, (variant_key,))
        
        updated = cur.rowcount
        if updated > 0:
            print(f"   🧹 Reset stale market data for {variant_key} ({updated} listings)")


def clear_all_stale_market_data(conn):
    """
    v6.2: Clears all stale market data older than 24 hours.
    """
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM market_data 
            WHERE calculated_at < NOW() - INTERVAL '24 hours'
        """)
        deleted_cache = cur.rowcount
        
        cur.execute("""
            UPDATE listings 
            SET market_value = NULL,
                buy_now_ceiling = NULL
            WHERE updated_at < NOW() - INTERVAL '24 hours'
              AND market_value IS NOT NULL
        """)
        reset_listings = cur.rowcount
        
        if deleted_cache > 0 or reset_listings > 0:
            print(f"🧹 Cleared stale market data: {deleted_cache} cache entries, "
                  f"{reset_listings} listings reset")


# ==============================================================================
# PRICE HISTORY
# ==============================================================================

def record_price_if_changed(conn, listing_id: str, new_price: float, bids_count: int = 0) -> bool:
    """
    Records price to history only if it changed.
    Returns: True if price changed, False if same
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT price 
            FROM price_history 
            WHERE listing_id = %s 
            ORDER BY observed_at DESC 
            LIMIT 1
        """, (listing_id,))
        
        result = cur.fetchone()
        last_price = float(result[0]) if result else None
    
    if last_price is None or abs(float(new_price) - last_price) > 0.01:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO price_history (listing_id, price, bids_count, observed_at)
                VALUES (%s, %s, %s, NOW())
            """, (listing_id, new_price, bids_count))
        
        if last_price:
            change_pct = ((float(new_price) - last_price) / last_price) * 100
            print(f"📉 Price change: {last_price:.0f} → {new_price:.0f} CHF ({change_pct:+.1f}%)")
        return True
    
    return False


def get_price_history(conn, listing_id: str) -> List[Dict]:
    """Gets all price history for a listing"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT price, bids_count, observed_at
            FROM price_history
            WHERE listing_id = %s
            ORDER BY observed_at ASC
        """, (listing_id,))
        
        return [
            {"price": float(row[0]), "bids_count": row[1], "observed_at": row[2]}
            for row in cur.fetchall()
        ]


# ==============================================================================
# COMPONENT CACHE (for bundles)
# ==============================================================================

def get_cached_component_price(conn, component_name: str) -> Optional[Dict]:
    """
    Gets cached component price if not expired.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT median_price, sample_size, price_range_low, price_range_high,
                   last_search_query, cached_at
            FROM component_cache
            WHERE component_name = %s
              AND expires_at > NOW()
        """, (component_name,))
        
        row = cur.fetchone()
        if not row:
            return None
        
        return {
            "median_price": float(row[0]) if row[0] else None,
            "sample_size": row[1],
            "price_range_low": float(row[2]) if row[2] else None,
            "price_range_high": float(row[3]) if row[3] else None,
            "last_search_query": row[4],
            "cached_at": row[5],
        }


def set_cached_component_price(
    conn, 
    component_name: str, 
    median_price: float,
    sample_size: int,
    price_range: tuple,
    search_query: str,
    cache_days: int = 30
):
    """Caches component price from Ricardo search"""
    expires = datetime.now() + timedelta(days=cache_days)
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO component_cache 
                (component_name, median_price, sample_size, price_range_low, 
                 price_range_high, last_search_query, cached_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (component_name)
            DO UPDATE SET 
                median_price = EXCLUDED.median_price,
                sample_size = EXCLUDED.sample_size,
                price_range_low = EXCLUDED.price_range_low,
                price_range_high = EXCLUDED.price_range_high,
                last_search_query = EXCLUDED.last_search_query,
                cached_at = NOW(),
                expires_at = EXCLUDED.expires_at
        """, (
            component_name, median_price, sample_size,
            price_range[0] if price_range else None,
            price_range[1] if price_range else None,
            search_query, expires
        ))
    
    print(f"💾 Cached component: {component_name} = {median_price} CHF (n={sample_size})")


# ==============================================================================
# v6.0: MARKET DATA CACHE
# ==============================================================================

def get_cached_market_data(conn, variant_key: str) -> Optional[Dict]:
    """v6.0: Gets cached market data for a variant if not expired."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT market_value, resale_price, sample_size, confidence, 
                   source, buy_now_ceiling, calculated_at
            FROM market_data
            WHERE variant_key = %s
              AND expires_at > NOW()
        """, (variant_key,))
        
        row = cur.fetchone()
        if not row:
            return None
        
        return {
            "market_value": float(row[0]) if row[0] else None,
            "resale_price": float(row[1]) if row[1] else None,
            "sample_size": row[2],
            "confidence": float(row[3]) if row[3] else None,
            "source": row[4],
            "buy_now_ceiling": float(row[5]) if row[5] else None,
            "calculated_at": row[6],
        }


def set_cached_market_data(
    conn,
    variant_key: str,
    market_value: float,
    resale_price: float,
    sample_size: int,
    confidence: float,
    source: str,
    buy_now_ceiling: Optional[float] = None,
    cache_days: int = 7,
):
    """v6.0: Caches market data for a variant."""
    expires = datetime.now() + timedelta(days=cache_days)
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO market_data 
                (variant_key, market_value, resale_price, sample_size, 
                 confidence, source, buy_now_ceiling, calculated_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (variant_key)
            DO UPDATE SET 
                market_value = EXCLUDED.market_value,
                resale_price = EXCLUDED.resale_price,
                sample_size = EXCLUDED.sample_size,
                confidence = EXCLUDED.confidence,
                source = EXCLUDED.source,
                buy_now_ceiling = EXCLUDED.buy_now_ceiling,
                calculated_at = NOW(),
                expires_at = EXCLUDED.expires_at
        """, (
            variant_key, market_value, resale_price, sample_size,
            confidence, source, buy_now_ceiling, expires
        ))
    
    print(f"💾 Cached market data: {variant_key} = {resale_price} CHF "
          f"(market={market_value}, n={sample_size}, conf={confidence:.0%})")


def clear_expired_market_data(conn):
    """v6.0: Removes expired market data entries"""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_data WHERE expires_at < NOW()")
        deleted = cur.rowcount
        if deleted > 0:
            print(f"🧹 Cleaned {deleted} expired market data entries")


# ==============================================================================
# MEDIAN CALCULATION
# ==============================================================================

def get_median_for_variant(conn, variant_key: str, days: int = 30) -> Optional[float]:
    """
    Calculates median price for a specific variant from DB.
    v6.0: Now prefers auction prices with bids over buy-now.
    """
    if not variant_key:
        return None
        
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                current_price_ricardo as price,
                bids_count,
                buy_now_price
            FROM listings
            WHERE variant_key = %s
                AND created_at > NOW() - INTERVAL '%s days'
                AND (current_price_ricardo IS NOT NULL OR buy_now_price IS NOT NULL)
        """, (variant_key, days))
        
        rows = cur.fetchall()
        
        if not rows:
            return None
        
        auction_prices_with_bids = []
        buy_now_prices = []
        
        for price, bids, buy_now in rows:
            if price and bids and bids >= 2:
                auction_prices_with_bids.append(float(price))
            if buy_now and buy_now > 0:
                buy_now_prices.append(float(buy_now))
        
        if len(auction_prices_with_bids) >= 2:
            auction_prices_with_bids.sort()
            n = len(auction_prices_with_bids)
            if n % 2 == 0:
                return (auction_prices_with_bids[n//2 - 1] + auction_prices_with_bids[n//2]) / 2
            else:
                return auction_prices_with_bids[n//2]
        
        if buy_now_prices:
            buy_now_prices.sort()
            n = len(buy_now_prices)
            if n % 2 == 0:
                return (buy_now_prices[n//2 - 1] + buy_now_prices[n//2]) / 2
            else:
                return buy_now_prices[n//2]
        
        return None


# ==============================================================================
# QUERY HELPERS
# ==============================================================================

def get_top_deals(conn, limit: int = 20, min_score: float = 6.0) -> List[Dict]:
    """Gets top deals sorted by score"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                listing_id, title, variant_key, 
                COALESCE(buy_now_price, current_price_ricardo) as price,
                resale_price_est, expected_profit, deal_score,
                bids_count, end_time, url,
                is_bundle, recommended_strategy, strategy_reason,
                market_value, price_source,
                seller_rating, shipping_cost, pickup_available
            FROM listings
            WHERE deal_score >= %s
            ORDER BY deal_score DESC
            LIMIT %s
        """, (min_score, limit))
        
        columns = [
            'listing_id', 'title', 'variant_key', 'price',
            'resale_price_est', 'expected_profit', 'deal_score',
            'bids_count', 'end_time', 'url',
            'is_bundle', 'recommended_strategy', 'strategy_reason',
            'market_value', 'price_source',
            'seller_rating', 'shipping_cost', 'pickup_available'
        ]
        
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_bundles(conn, limit: int = 50) -> List[Dict]:
    """Gets all bundle listings"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                listing_id, title, 
                COALESCE(buy_now_price, current_price_ricardo) as price,
                bundle_components, resale_price_bundle, expected_profit,
                deal_score, recommended_strategy, url
            FROM listings
            WHERE is_bundle = TRUE
            ORDER BY deal_score DESC
            LIMIT %s
        """, (limit,))
        
        columns = [
            'listing_id', 'title', 'price', 'bundle_components',
            'resale_price_bundle', 'expected_profit', 'deal_score',
            'recommended_strategy', 'url'
        ]
        
        results = []
        for row in cur.fetchall():
            d = dict(zip(columns, row))
            if d.get('bundle_components') and isinstance(d['bundle_components'], str):
                try:
                    d['bundle_components'] = json.loads(d['bundle_components'])
                except:
                    pass
            results.append(d)
        
        return results


# ==============================================================================
# CLEANUP
# ==============================================================================

def cleanup_old_listings(conn, days: int = 30):
    """Deletes listings older than X days"""
    cutoff = datetime.utcnow() - timedelta(days=days)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM listings WHERE created_at < %s", (cutoff,))
        deleted = cur.rowcount
        conn.commit()

        if deleted > 0:
            print(f"🧹 Deleted {deleted} old listings (>{days} days)")
        else:
            print("🧹 No old listings to delete")


def cleanup_expired_component_cache(conn):
    """Removes expired component cache entries"""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM component_cache WHERE expires_at < NOW()")
        deleted = cur.rowcount
        if deleted > 0:
            print(f"🧹 Cleaned {deleted} expired component cache entries")