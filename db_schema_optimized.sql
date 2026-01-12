-- ============================================================================
-- OPTIMIZED DATABASE SCHEMA v7.3.5
-- ============================================================================
-- Changes:
-- 1. Reordered columns for logical grouping (SELECT * readability)
-- 2. Added missing columns (run_id, web_search_used, cache_hit, ai_cost_usd)
-- 3. Removed redundant columns (detected_product)
-- 4. Better indexing strategy
-- ============================================================================

-- MIGRATION SCRIPT: Reorder columns by creating new table and copying data
-- WARNING: This requires downtime! Run during maintenance window.

BEGIN;

-- Step 1: Rename old table
ALTER TABLE listings RENAME TO listings_old;

-- Step 2: Create new table with optimized column order
CREATE TABLE listings (
    -- ========================================================================
    -- GROUP 1: IDENTIFICATION (Most important for joins/lookups)
    -- ========================================================================
    id                      SERIAL PRIMARY KEY,
    platform                TEXT NOT NULL,
    listing_id              TEXT NOT NULL,
    title                   TEXT,
    variant_key             TEXT,
    
    -- ========================================================================
    -- GROUP 2: PRICES & PROFIT (Most important for analysis!)
    -- ========================================================================
    buy_now_price           NUMERIC,
    current_price_ricardo   NUMERIC,
    predicted_final_price   NUMERIC,
    new_price               NUMERIC,
    resale_price_est        NUMERIC,
    resale_price_bundle     NUMERIC,
    expected_profit         NUMERIC,
    market_value            NUMERIC,
    buy_now_ceiling         NUMERIC,
    shipping_cost           NUMERIC,
    price_source            TEXT,
    
    -- ========================================================================
    -- GROUP 3: DEAL EVALUATION
    -- ========================================================================
    deal_score              NUMERIC,
    recommended_strategy    TEXT,
    strategy_reason         TEXT,
    market_based_resale     BOOLEAN DEFAULT FALSE,
    market_sample_size      INTEGER,
    
    -- ========================================================================
    -- GROUP 4: BUNDLE INFO
    -- ========================================================================
    is_bundle               BOOLEAN DEFAULT FALSE,
    bundle_components       JSONB,
    
    -- ========================================================================
    -- GROUP 5: AUCTION INFO
    -- ========================================================================
    bids_count              INTEGER,
    hours_remaining         FLOAT,
    end_time                TIMESTAMP,
    
    -- ========================================================================
    -- GROUP 6: LOCATION & TRANSPORT
    -- ========================================================================
    location                TEXT,
    postal_code             TEXT,
    shipping                TEXT,
    transport_car           BOOLEAN,
    pickup_available        BOOLEAN,
    seller_rating           INTEGER,
    
    -- ========================================================================
    -- GROUP 7: METADATA (NEW v7.3.5)
    -- ========================================================================
    run_id                  TEXT,           -- NEW: Which run created this?
    web_search_used         BOOLEAN,        -- NEW: Was web search used?
    cache_hit               BOOLEAN,        -- NEW: Was it a cache hit?
    ai_cost_usd             NUMERIC,        -- NEW: AI cost for this listing
    
    -- ========================================================================
    -- GROUP 8: TIMESTAMPS
    -- ========================================================================
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW(),
    
    -- ========================================================================
    -- GROUP 9: LONG TEXT & URLs (Last for SELECT * readability)
    -- ========================================================================
    description             TEXT,
    ai_notes                TEXT,
    image_url               TEXT,
    url                     TEXT,
    
    -- ========================================================================
    -- CONSTRAINTS
    -- ========================================================================
    UNIQUE (platform, listing_id)
);

-- Step 3: Copy data from old table (map old columns to new positions)
INSERT INTO listings (
    id, platform, listing_id, title, variant_key,
    buy_now_price, current_price_ricardo, predicted_final_price,
    new_price, resale_price_est, resale_price_bundle, expected_profit,
    market_value, buy_now_ceiling, shipping_cost, price_source,
    deal_score, recommended_strategy, strategy_reason,
    market_based_resale, market_sample_size,
    is_bundle, bundle_components,
    bids_count, hours_remaining, end_time,
    location, postal_code, shipping, transport_car, pickup_available, seller_rating,
    created_at, updated_at,
    description, ai_notes, image_url, url
)
SELECT 
    id, platform, listing_id, title, variant_key,
    buy_now_price, current_price_ricardo, predicted_final_price,
    new_price, resale_price_est, resale_price_bundle, expected_profit,
    market_value, buy_now_ceiling, shipping_cost, price_source,
    deal_score, recommended_strategy, strategy_reason,
    market_based_resale, market_sample_size,
    is_bundle, bundle_components,
    bids_count, hours_remaining, end_time,
    location, postal_code, shipping, transport_car, pickup_available, seller_rating,
    created_at, updated_at,
    description, ai_notes, image_url, url
FROM listings_old;

-- Step 4: Update sequence to match max id
SELECT setval('listings_id_seq', (SELECT MAX(id) FROM listings));

-- Step 5: Create optimized indexes
CREATE INDEX idx_listings_variant_key ON listings(variant_key);
CREATE INDEX idx_listings_bundle ON listings(is_bundle) WHERE is_bundle = TRUE;
CREATE INDEX idx_listings_strategy ON listings(recommended_strategy);
CREATE INDEX idx_listings_deal_score ON listings(deal_score DESC NULLS LAST);
CREATE INDEX idx_listings_profit ON listings(expected_profit DESC NULLS LAST);
CREATE INDEX idx_listings_run_id ON listings(run_id);  -- NEW: Track by run
CREATE INDEX idx_listings_price_source ON listings(price_source);  -- NEW: Analyze price sources
CREATE INDEX idx_listings_created_at ON listings(created_at DESC);  -- NEW: Time-based queries

-- Step 6: Drop old table
DROP TABLE listings_old;

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Check column order
SELECT column_name, ordinal_position, data_type 
FROM information_schema.columns 
WHERE table_name = 'listings' 
ORDER BY ordinal_position;

-- Check row count
SELECT COUNT(*) FROM listings;

-- Test SELECT * (should show prices together now!)
SELECT * FROM listings LIMIT 1;
