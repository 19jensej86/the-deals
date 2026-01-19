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
# v11: UNIFIED SCHEMA - "One Product = One Row"
# ==============================================================================
# Single listings table that represents:
# - One row per product (not per Ricardo listing)
# - Bundles: multiple rows with same bundle_id
# - Full pricing, websearch, and audit data inline
# - No separate products/pricing tables needed

SCHEMA_VERSION = "v11.1"

# Unified listings table - One Product = One Row
LISTINGS_V11_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    -- ========================================================================
    -- PRIMARY KEY & RUN TRACKING
    -- ========================================================================
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    
    -- ========================================================================
    -- SOURCE LISTING (Ricardo)
    -- ========================================================================
    platform TEXT NOT NULL DEFAULT 'ricardo',
    source_listing_id TEXT NOT NULL,  -- Ricardo listing ID
    title TEXT,
    description TEXT,
    url TEXT,
    image_url TEXT,
    
    -- ========================================================================
    -- PRODUCT IDENTIFICATION
    -- ========================================================================
    product_name TEXT,
    cleaned_name TEXT,
    product_type TEXT,
    variant_key TEXT,
    
    -- ========================================================================
    -- QUANTITY & BUNDLE LOGIC
    -- ========================================================================
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    bundle_id INTEGER,  -- NULL = single product, unique ID = bundle group
    is_bundle_component BOOLEAN DEFAULT FALSE,
    
    -- ========================================================================
    -- PRICING (Total = for quantity in this row)
    -- ========================================================================
    new_price_total NUMERIC,
    new_price_unit NUMERIC,
    resale_price_est_total NUMERIC,
    resale_price_unit NUMERIC,
    
    -- Ricardo prices
    buy_now_price NUMERIC,
    current_price_ricardo NUMERIC,
    predicted_final_price NUMERIC,
    
    -- ========================================================================
    -- PRICE SOURCE & AUDIT
    -- ========================================================================
    price_source TEXT NOT NULL DEFAULT 'no_price',
    price_confidence NUMERIC,
    web_sources JSONB,  -- Full audit trail from websearch
    quantity_parsed_from_snippet BOOLEAN DEFAULT FALSE,
    
    -- ========================================================================
    -- MARKET DATA
    -- ========================================================================
    market_value NUMERIC,
    market_sample_size INTEGER DEFAULT 0,
    market_based BOOLEAN DEFAULT FALSE,
    buy_now_ceiling NUMERIC,
    
    -- ========================================================================
    -- DEAL EVALUATION
    -- ========================================================================
    expected_profit NUMERIC,
    deal_score NUMERIC,
    recommended_strategy TEXT,
    strategy_reason TEXT,
    
    -- ========================================================================
    -- AUCTION INFO
    -- ========================================================================
    bids_count INTEGER,
    hours_remaining NUMERIC,
    end_time TIMESTAMP,
    
    -- ========================================================================
    -- LOCATION & TRANSPORT
    -- ========================================================================
    location TEXT,
    postal_code TEXT,
    shipping TEXT,
    shipping_cost NUMERIC,
    pickup_available BOOLEAN,
    transport_car BOOLEAN,
    
    -- ========================================================================
    -- SELLER INFO
    -- ========================================================================
    seller_rating INTEGER,
    
    -- ========================================================================
    -- METADATA & OBSERVABILITY
    -- ========================================================================
    web_search_used BOOLEAN DEFAULT FALSE,
    vision_used BOOLEAN DEFAULT FALSE,
    cache_hit BOOLEAN DEFAULT FALSE,
    ai_cost_usd NUMERIC,
    ai_notes TEXT,
    
    -- ========================================================================
    -- TIMESTAMPS
    -- ========================================================================
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- ========================================================================
    -- CONSTRAINTS
    -- ========================================================================
    CONSTRAINT valid_price_source CHECK (
        price_source IN (
            'web_median', 'web_single', 'web_median_qty_adjusted',
            'ai_estimate', 'query_baseline', 'buy_now_fallback',
            'bundle_aggregate', 'market_auction', 'no_price'
        )
    ),
    CONSTRAINT valid_quantity CHECK (quantity >= 1)
);
"""

# Indexes for the unified listings table
LISTINGS_V11_INDEXES = """
-- Run tracking
CREATE INDEX IF NOT EXISTS idx_listings_run ON listings(run_id);
CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC);

-- Source listing lookup
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(platform, source_listing_id);

-- Product identification
CREATE INDEX IF NOT EXISTS idx_listings_product_type ON listings(product_type);
CREATE INDEX IF NOT EXISTS idx_listings_variant ON listings(variant_key);
CREATE INDEX IF NOT EXISTS idx_listings_cleaned_name ON listings(cleaned_name);

-- Bundle grouping
CREATE INDEX IF NOT EXISTS idx_listings_bundle ON listings(bundle_id) WHERE bundle_id IS NOT NULL;

-- Deal evaluation
CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(deal_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_listings_profit ON listings(expected_profit DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_listings_strategy ON listings(recommended_strategy);

-- Price source analysis
CREATE INDEX IF NOT EXISTS idx_listings_price_source ON listings(price_source);
"""


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
# v11: UNIFIED SCHEMA MANAGEMENT - "One Product = One Row"
# ==============================================================================

def ensure_schema_v2(conn, reset_schema: bool = False):
    """
    v11.1: Ensures unified listings table exists (One Product = One Row).
    
    Args:
        conn: Database connection
        reset_schema: If True, drops and recreates table (DANGEROUS - only for dev/testing)
    
    IMPORTANT: By default, this creates the table IF NOT EXISTS.
    Data persistence is managed separately via clear_listings(run_id).
    """
    with conn.cursor() as cur:
        if reset_schema:
            # DANGEROUS: Only use for development/testing
            print(f"⚠️ RESET_SCHEMA=True: Dropping listings table...")
            cur.execute("DROP TABLE IF EXISTS listings CASCADE;")
            conn.commit()
            print("   🗑️ listings table dropped")
        
        # Create unified listings table (idempotent)
        print(f"📦 Ensuring v11.1 unified listings table exists...")
        cur.execute(LISTINGS_V11_SCHEMA)
        print("   ✅ listings table ready")
        
        # Create indexes (idempotent)
        for idx_sql in LISTINGS_V11_INDEXES.strip().split(";"):
            if idx_sql.strip():
                try:
                    cur.execute(idx_sql)
                except Exception as e:
                    pass  # Index already exists
        print("   ✅ Indexes ready")
        
        conn.commit()
        print(f"✅ v11.1 unified schema initialized")


def clear_listings(conn, run_id: str = None):
    """
    v11.1: Clears listings table for a specific run or all data.
    
    Args:
        conn: Database connection
        run_id: If provided, only clears data for this run. If None, clears all.
    """
    with conn.cursor() as cur:
        if run_id:
            cur.execute("DELETE FROM listings WHERE run_id = %s", (run_id,))
            print(f"🧹 Cleared run: {run_id}")
        else:
            cur.execute("DELETE FROM listings")
            print("🧹 Cleared all listings")
        conn.commit()


# ==============================================================================
# v11.1: UNIFIED LISTING INSERT - "One Product = One Row"
# ==============================================================================


def insert_listing(conn, run_id: str, data: Dict[str, Any]) -> int:
    """
    v11.1: Inserts a product row into the unified listings table.
    
    This represents ONE PRODUCT (not one Ricardo listing).
    For bundles, call this multiple times with same bundle_id.
    
    Args:
        conn: Database connection
        run_id: Current run ID
        data: Product data dict with all fields from unified schema
    
    Returns:
        The listing row ID
    """
    # Serialize JSONB fields
    web_sources = data.get("web_sources")
    if web_sources and isinstance(web_sources, list):
        web_sources = json.dumps(web_sources, ensure_ascii=False)
    
    # Validate price_source
    valid_sources = {
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    }
    price_source = data.get("price_source", "no_price")
    if price_source not in valid_sources:
        price_source = "no_price"
    
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO listings (
                run_id, platform, source_listing_id, title, description, url, image_url,
                product_name, cleaned_name, product_type, variant_key,
                quantity, bundle_id, is_bundle_component,
                new_price_total, new_price_unit, resale_price_est_total, resale_price_unit,
                buy_now_price, current_price_ricardo, predicted_final_price,
                price_source, price_confidence, web_sources, quantity_parsed_from_snippet,
                market_value, market_sample_size, market_based, buy_now_ceiling,
                expected_profit, deal_score, recommended_strategy, strategy_reason,
                bids_count, hours_remaining, end_time,
                location, postal_code, shipping, shipping_cost, pickup_available, transport_car,
                seller_rating,
                web_search_used, vision_used, cache_hit, ai_cost_usd, ai_notes
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s,
                %s, %s, %s, %s, %s
            )
            RETURNING id
        """, (
            run_id,
            data.get("platform", "ricardo"),
            data.get("source_listing_id"),
            data.get("title"),
            data.get("description"),
            data.get("url"),
            data.get("image_url"),
            data.get("product_name"),
            data.get("cleaned_name"),
            data.get("product_type"),
            data.get("variant_key"),
            data.get("quantity", 1),
            data.get("bundle_id"),
            data.get("is_bundle_component", False),
            data.get("new_price_total"),
            data.get("new_price_unit"),
            data.get("resale_price_est_total"),
            data.get("resale_price_unit"),
            data.get("buy_now_price"),
            data.get("current_price_ricardo"),
            data.get("predicted_final_price"),
            price_source,
            data.get("price_confidence"),
            web_sources,
            data.get("quantity_parsed_from_snippet", False),
            data.get("market_value"),
            data.get("market_sample_size", 0),
            data.get("market_based", False),
            data.get("buy_now_ceiling"),
            data.get("expected_profit"),
            data.get("deal_score"),
            data.get("recommended_strategy"),
            data.get("strategy_reason"),
            data.get("bids_count"),
            data.get("hours_remaining"),
            data.get("end_time"),
            data.get("location"),
            data.get("postal_code"),
            data.get("shipping"),
            data.get("shipping_cost"),
            data.get("pickup_available"),
            data.get("transport_car"),
            data.get("seller_rating"),
            data.get("web_search_used", False),
            data.get("vision_used", False),
            data.get("cache_hit", False),
            data.get("ai_cost_usd"),
            data.get("ai_notes"),
        ))
        listing_id = cur.fetchone()[0]
    
    return listing_id


# ==============================================================================
# v11.1: QUERY & EXPORT HELPERS (Unified Schema)
# ==============================================================================

def get_listings(conn, run_id: str = None, 
                 min_score: float = None,
                 strategy: str = None,
                 limit: int = 100) -> List[Dict]:
    """
    v11.1: Gets listings (products) from unified table.
    
    Args:
        run_id: Filter by run (optional)
        min_score: Minimum deal_score filter (optional)
        strategy: Filter by recommended_strategy (optional)
        limit: Max rows to return
    
    Returns:
        List of listing dicts
    """
    conditions = []
    params = []
    
    if run_id:
        conditions.append("run_id = %s")
        params.append(run_id)
    if min_score is not None:
        conditions.append("deal_score >= %s")
        params.append(min_score)
    if strategy:
        conditions.append("recommended_strategy = %s")
        params.append(strategy)
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT *
            FROM listings
            {where_clause}
            ORDER BY deal_score DESC NULLS LAST, expected_profit DESC NULLS LAST
            LIMIT %s
        """, params)
        
        columns = [desc[0] for desc in cur.description]
        results = []
        for row in cur.fetchall():
            d = dict(zip(columns, row))
            # Parse JSONB fields
            if d.get('web_sources') and isinstance(d['web_sources'], str):
                try:
                    d['web_sources'] = json.loads(d['web_sources'])
                except:
                    pass
            results.append(d)
        
        return results


def get_bundle_groups(conn, run_id: str = None, limit: int = 50) -> List[Dict]:
    """
    v11.1: Gets all bundle groups with their components.
    """
    conditions = ["bundle_id IS NOT NULL"]
    params = []
    
    if run_id:
        conditions.append("run_id = %s")
        params.append(run_id)
    
    where_clause = "WHERE " + " AND ".join(conditions)
    params.append(limit)
    
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT bundle_id, COUNT(*) as component_count
            FROM listings
            {where_clause}
            GROUP BY bundle_id
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
            LIMIT %s
        """, params)
        
        return [{"bundle_id": row[0], "component_count": row[1]} 
                for row in cur.fetchall()]


def export_listings_json(conn, run_id: str, filepath: str = "last_run_listings.json"):
    """
    v11.1: Exports listings to JSON file.
    """
    listings = get_listings(conn, run_id=run_id, limit=10000)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"📁 Exported {len(listings)} listings to {filepath}")
    return len(listings)


def export_listings_csv(conn, run_id: str, filepath: str = "last_run_listings.csv"):
    """
    v11.1: Exports listings to CSV file.
    """
    import csv
    
    listings = get_listings(conn, run_id=run_id, limit=10000)
    
    if not listings:
        print(f"⚠️ No listings to export")
        return 0
    
    # Flatten web_sources for CSV
    for listing in listings:
        if listing.get('web_sources'):
            listing['web_sources'] = json.dumps(listing['web_sources'])
    
    fieldnames = list(listings[0].keys())
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(listings)
    
    print(f"📁 Exported {len(listings)} listings to {filepath}")
    return len(listings)


# ==============================================================================
# UPSERT (Legacy - kept for backward compatibility)
# ==============================================================================

def upsert_listing(conn, data: Dict[str, Any]):
    """
    Inserts a listing into the unified listings table.
    
    v11.1: Changed from UPSERT to simple INSERT.
    WHY: The unified listings table has NO unique constraint by design.
         "One Product = One Row" allows duplicates (e.g., bundles).
         Deduplication is handled by run_id + testing mode cleanup.
    
    FIELD MAPPING: main.py uses "listing_id" → DB expects "source_listing_id"
    
    v7.3.5: Added run_id, web_search_used, cache_hit, ai_cost_usd fields.
    v7.0: Added seller_rating, shipping_cost, pickup_available fields.
    """
    # Map incoming data fields to database columns
    # CRITICAL: main.py uses "listing_id", but unified schema expects "source_listing_id"
    field_mapping = {
        "platform": "platform",
        "listing_id": "source_listing_id",  # MAPPING FIX
        "title": "title",
        "description": "description",
        "location": "location",
        "postal_code": "postal_code",
        "shipping": "shipping",
        "transport_car": "transport_car",
        "end_time": "end_time",
        "image_url": "image_url",
        "url": "url",
        "ai_notes": None,  # SKIP - ai_notes is legacy, strategy_reason comes separately
        "buy_now_price": "buy_now_price",
        "current_price_ricardo": "current_price_ricardo",
        "bids_count": "bids_count",
        "new_price": "new_price_total",  # new_price → new_price_total
        "resale_price_est": "resale_price_est_total",  # resale_price_est → resale_price_est_total
        "expected_profit": "expected_profit",
        "deal_score": "deal_score",
        "variant_key": "variant_key",
        "predicted_final_price": "predicted_final_price",
        "prediction_confidence": None,  # SKIP - not in unified schema
        "is_bundle": "is_bundle_component",  # is_bundle → is_bundle_component
        "bundle_components": None,  # SKIP - this is JSONB data, not bundle_id
        "resale_price_bundle": None,  # SKIP - already in resale_price_est_total
        "recommended_strategy": "recommended_strategy",
        "strategy_reason": "strategy_reason",
        "market_based_resale": "market_based",  # market_based_resale → market_based
        "market_sample_size": "market_sample_size",
        "market_value": "market_value",
        "price_source": "price_source",
        "buy_now_ceiling": "buy_now_ceiling",
        "hours_remaining": "hours_remaining",
        "seller_rating": "seller_rating",
        "shipping_cost": "shipping_cost",
        "pickup_available": "pickup_available",
        "run_id": "run_id",
        "web_search_used": "web_search_used",
        "cache_hit": None,  # SKIP - not in unified schema
        "ai_cost_usd": None,  # SKIP - not in unified schema
        "vision_used": "vision_used",
        "cleaned_title": "cleaned_name",  # cleaned_title → cleaned_name
        "extraction_confidence": None,  # SKIP - v10 field not in unified schema
        "bundle_type_v10": None,  # SKIP - v10 field not in unified schema
    }
    
    # Build SQL fields and values based on what's in data
    db_fields = []
    values = []
    
    for data_key, db_col in field_mapping.items():
        if data_key in data:
            # Skip fields not in unified schema (db_col is None)
            if db_col is None:
                continue
            
            v = data.get(data_key)
            
            # Convert any dict or list to JSON string
            if v is not None and isinstance(v, (dict, list)):
                type_name = "dict" if isinstance(v, dict) else "list"
                print(f"   🗄️ DB normalize: field={db_col} ({type_name} → JSON)")
                v = json.dumps(v, ensure_ascii=False)
            
            db_fields.append(db_col)
            values.append(v)
    
    # DEFENSIVE VALIDATION: Check NOT NULL constraints BEFORE database insert
    # This prevents cryptic PostgreSQL errors and provides clear diagnostics
    required_fields = {
        "run_id": "Run ID must be set",
        "platform": "Platform must be set (default: 'ricardo')",
        "source_listing_id": "Source listing ID (Ricardo ID) is required",
    }
    
    missing_fields = []
    for req_field, error_msg in required_fields.items():
        if req_field not in db_fields:
            missing_fields.append(f"  • {req_field}: {error_msg}")
        else:
            idx = db_fields.index(req_field)
            if values[idx] is None or (isinstance(values[idx], str) and not values[idx].strip()):
                missing_fields.append(f"  • {req_field}: {error_msg} (value is None or empty)")
    
    # CRITICAL: Validate price_source against CHECK constraint
    # Schema enforces: price_source IN ('web_median', 'web_single', 'web_median_qty_adjusted',
    #                                    'ai_estimate', 'query_baseline', 'buy_now_fallback',
    #                                    'bundle_aggregate', 'market_auction', 'no_price')
    valid_price_sources = {
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    }
    
    if "price_source" in db_fields:
        idx = db_fields.index("price_source")
        price_source_value = values[idx]
        if price_source_value not in valid_price_sources:
            missing_fields.append(
                f"  • price_source: Invalid value '{price_source_value}'\n"
                f"    Allowed: {', '.join(sorted(valid_price_sources))}"
            )
    
    if missing_fields:
        title = data.get('title', 'UNKNOWN')[:50]
        error_report = "\n".join(missing_fields)
        raise ValueError(
            f"❌ PRE-INSERT VALIDATION FAILED for listing: {title}\n"
            f"Missing or invalid required fields:\n{error_report}\n"
            f"Data keys present: {list(data.keys())[:10]}"
        )
    
    placeholders = ", ".join(["%s"] * len(values))

    # v11.1: Simple INSERT (no ON CONFLICT)
    # The unified schema has no unique constraint - duplicates are OK
    # Testing mode clears data by run_id, normal mode keeps history
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO listings ({', '.join(db_fields)})
            VALUES ({placeholders});
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
        WHERE source_listing_id = %s AND platform = 'ricardo'
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
            WHERE source_listing_id = %s AND platform = 'ricardo'
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