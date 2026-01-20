-- =============================================================================
-- DealFinder Schema v2.0 - Clean Domain Model
-- =============================================================================
-- Design Principles:
--   1. One row = one thing
--   2. NULLs mean "unknown", not "not applicable"
--   3. Reporting-first (every column answers a business question)
--   4. No debug data in business tables
--   5. Derived values computed at query time
-- =============================================================================

-- Drop existing tables (user will do this manually)
-- DROP TABLE IF EXISTS bundle_items, deals, listings, products, runs, price_cache, price_history CASCADE;

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PRODUCTS: Query-agnostic product identity
-- -----------------------------------------------------------------------------
-- Purpose: Reusable product definitions across listings and runs
-- UI Use: Product search, product performance dashboard
-- -----------------------------------------------------------------------------
CREATE TABLE products (
    id              SERIAL PRIMARY KEY,
    
    -- Identity (immutable)
    variant_key     TEXT NOT NULL UNIQUE,        -- "apple_iphone_12_mini_128gb"
    display_name    TEXT NOT NULL,               -- "Apple iPhone 12 mini 128GB"
    brand           TEXT,                        -- "Apple"
    category        TEXT,                        -- "smartphone", "fitness", "audio"
    
    -- Reference pricing (mutable, from websearch)
    reference_price NUMERIC,                     -- Typical NEW price (CHF)
    resale_estimate NUMERIC,                     -- Typical RESALE price (CHF)
    price_updated   TIMESTAMP,                   -- When prices last refreshed
    
    -- Metadata
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE products IS 'Query-agnostic product identity. Reusable across listings and runs.';
COMMENT ON COLUMN products.variant_key IS 'Normalized product identifier, e.g., apple_iphone_12_mini_128gb';
COMMENT ON COLUMN products.reference_price IS 'Typical new/retail price in CHF from websearch';
COMMENT ON COLUMN products.resale_estimate IS 'Typical resale value in CHF (what you can sell for)';

CREATE UNIQUE INDEX idx_products_variant ON products(variant_key);
CREATE INDEX idx_products_brand ON products(brand);
CREATE INDEX idx_products_category ON products(category);


-- -----------------------------------------------------------------------------
-- LISTINGS: Raw marketplace facts
-- -----------------------------------------------------------------------------
-- Purpose: What we scraped from Ricardo. Source of truth.
-- UI Use: Listing detail view, "raw data" tab
-- -----------------------------------------------------------------------------
CREATE TABLE listings (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,               -- Which run found this
    
    -- Source identity
    platform            TEXT NOT NULL DEFAULT 'ricardo',
    source_id           TEXT NOT NULL,               -- Ricardo listing ID
    url                 TEXT NOT NULL,               -- Direct link to listing
    
    -- Content
    title               TEXT NOT NULL,               -- Original listing title
    image_url           TEXT,                        -- Thumbnail URL
    
    -- Product link (NULL if product not identified)
    product_id          INTEGER REFERENCES products(id),
    
    -- Pricing (what seller is asking)
    buy_now_price       NUMERIC,                     -- Sofortkauf price (NULL if auction-only)
    current_bid         NUMERIC,                     -- Current auction price
    
    -- Auction state
    bids_count          INTEGER DEFAULT 0,
    end_time            TIMESTAMP,                   -- Auction end (NULL for Sofortkauf-only)
    
    -- Location & shipping
    location            TEXT,                        -- City/region
    shipping_cost       NUMERIC,                     -- Shipping cost in CHF
    pickup_available    BOOLEAN DEFAULT FALSE,
    
    -- Seller
    seller_rating       INTEGER,                     -- Percentage 0-100
    
    -- Lifecycle
    first_seen          TIMESTAMP DEFAULT NOW(),
    last_seen           TIMESTAMP DEFAULT NOW(),
    
    -- Prevent duplicate source listings
    CONSTRAINT uq_listing_source UNIQUE (platform, source_id)
);

COMMENT ON TABLE listings IS 'Raw marketplace facts from Ricardo. One row per source listing.';
COMMENT ON COLUMN listings.source_id IS 'Ricardo listing ID (from URL)';
COMMENT ON COLUMN listings.current_bid IS 'Current auction price (changes over time)';
COMMENT ON COLUMN listings.end_time IS 'Auction end time. NULL for Sofortkauf-only listings.';

CREATE INDEX idx_listings_run ON listings(run_id);
CREATE INDEX idx_listings_product ON listings(product_id);
CREATE INDEX idx_listings_end_time ON listings(end_time) WHERE end_time IS NOT NULL;
CREATE INDEX idx_listings_platform_source ON listings(platform, source_id);


-- -----------------------------------------------------------------------------
-- DEALS: Evaluated opportunities
-- -----------------------------------------------------------------------------
-- Purpose: The actionable output. What you decide to buy/watch/skip.
-- UI Use: MAIN DASHBOARD, deal cards, action lists
-- -----------------------------------------------------------------------------
CREATE TABLE deals (
    id                  BIGSERIAL PRIMARY KEY,
    
    -- Links
    listing_id          BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id),
    run_id              TEXT NOT NULL,
    
    -- === THE IMPORTANT STUFF ===
    
    -- Money
    cost_estimate       NUMERIC NOT NULL,            -- What you'd pay (buy_now or predicted)
    market_value        NUMERIC NOT NULL,            -- What you'd sell for (resale estimate)
    expected_profit     NUMERIC NOT NULL,            -- market_value - cost - fees
    profit_margin_pct   NUMERIC,                     -- (profit / cost) * 100
    
    -- Score
    deal_score          NUMERIC NOT NULL,            -- 1-10 rating
    
    -- Action
    strategy            TEXT NOT NULL,               -- 'buy_now', 'bid_now', 'watch', 'skip'
    strategy_reason     TEXT,                        -- Human explanation "🔥 Buy now! Profit 86 CHF"
    
    -- Transparency
    price_source        TEXT NOT NULL,               -- 'web_median', 'ai_estimate', 'query_baseline', etc.
    
    -- Bundle handling
    is_bundle           BOOLEAN DEFAULT FALSE,
    bundle_id           INTEGER,                     -- Groups components of same bundle
    
    -- Lifecycle
    status              TEXT DEFAULT 'active',       -- 'active', 'expired', 'purchased', 'archived'
    evaluated_at        TIMESTAMP DEFAULT NOW(),
    expires_at          TIMESTAMP,                   -- Copied from listing.end_time for convenience
    
    -- Constraints
    CONSTRAINT valid_strategy CHECK (strategy IN ('buy_now', 'bid_now', 'watch', 'skip')),
    CONSTRAINT valid_status CHECK (status IN ('active', 'expired', 'purchased', 'archived')),
    CONSTRAINT valid_price_source CHECK (price_source IN (
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    ))
);

COMMENT ON TABLE deals IS 'Evaluated opportunities. The actionable output you make decisions on.';
COMMENT ON COLUMN deals.cost_estimate IS 'What you would pay: buy_now_price or predicted final auction price';
COMMENT ON COLUMN deals.market_value IS 'What you could sell for: resale estimate from websearch/AI';
COMMENT ON COLUMN deals.expected_profit IS 'market_value - cost_estimate - platform_fees';
COMMENT ON COLUMN deals.strategy IS 'Recommended action: buy_now, bid_now, watch, or skip';
COMMENT ON COLUMN deals.bundle_id IS 'Groups multiple rows that belong to same bundle listing';

CREATE INDEX idx_deals_run ON deals(run_id);
CREATE INDEX idx_deals_active_score ON deals(deal_score DESC) WHERE status = 'active';
CREATE INDEX idx_deals_active_profit ON deals(expected_profit DESC) WHERE status = 'active';
CREATE INDEX idx_deals_strategy ON deals(strategy) WHERE status = 'active';
CREATE INDEX idx_deals_product ON deals(product_id);
CREATE INDEX idx_deals_listing ON deals(listing_id);
CREATE INDEX idx_deals_bundle ON deals(bundle_id) WHERE bundle_id IS NOT NULL;


-- -----------------------------------------------------------------------------
-- BUNDLE_ITEMS: Explicit bundle structure
-- -----------------------------------------------------------------------------
-- Purpose: Links a bundle deal to its component products with quantities
-- UI Use: Bundle breakdown view, per-item value display
-- -----------------------------------------------------------------------------
CREATE TABLE bundle_items (
    id              SERIAL PRIMARY KEY,
    
    -- Parent bundle (matches deals.bundle_id)
    bundle_id       INTEGER NOT NULL,
    
    -- Component
    product_id      INTEGER REFERENCES products(id),
    product_name    TEXT NOT NULL,                   -- Display name (even without product_id)
    quantity        INTEGER NOT NULL DEFAULT 1,
    
    -- Per-item pricing
    unit_value      NUMERIC,                         -- Estimated value per item
    
    CONSTRAINT valid_quantity CHECK (quantity >= 1)
);

COMMENT ON TABLE bundle_items IS 'Explicit bundle structure. Links bundle to component products.';
COMMENT ON COLUMN bundle_items.bundle_id IS 'Matches deals.bundle_id to group components';
COMMENT ON COLUMN bundle_items.unit_value IS 'Estimated resale value per unit';

CREATE INDEX idx_bundle_items_bundle ON bundle_items(bundle_id);
CREATE INDEX idx_bundle_items_product ON bundle_items(product_id);


-- =============================================================================
-- OPERATIONAL TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- RUNS: Pipeline execution metadata
-- -----------------------------------------------------------------------------
-- Purpose: Track when runs happened, what they cost, how they performed
-- UI Use: Run history page, cost tracking dashboard
-- -----------------------------------------------------------------------------
CREATE TABLE runs (
    id              TEXT PRIMARY KEY,                -- UUID or timestamp-based
    
    -- Timing
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP,
    duration_sec    INTEGER,
    
    -- Configuration
    mode            TEXT NOT NULL,                   -- 'test' or 'prod'
    queries         JSONB,                           -- Search queries used
    
    -- Results
    listings_found  INTEGER DEFAULT 0,
    deals_created   INTEGER DEFAULT 0,
    profitable_deals INTEGER DEFAULT 0,
    
    -- Cost
    ai_cost_usd     NUMERIC DEFAULT 0,
    websearch_calls INTEGER DEFAULT 0,
    
    -- Status
    status          TEXT DEFAULT 'running',          -- 'running', 'completed', 'failed'
    error_message   TEXT,
    
    CONSTRAINT valid_mode CHECK (mode IN ('test', 'prod')),
    CONSTRAINT valid_run_status CHECK (status IN ('running', 'completed', 'failed'))
);

COMMENT ON TABLE runs IS 'Pipeline execution metadata. One row per python main.py invocation.';

CREATE INDEX idx_runs_started ON runs(started_at DESC);
CREATE INDEX idx_runs_status ON runs(status);


-- -----------------------------------------------------------------------------
-- PRICE_CACHE: Temporary websearch results (disposable)
-- -----------------------------------------------------------------------------
-- Purpose: Avoid re-searching same product within TTL
-- UI Use: None (internal cache)
-- -----------------------------------------------------------------------------
CREATE TABLE price_cache (
    variant_key     TEXT PRIMARY KEY,
    
    new_price       NUMERIC,                         -- Reference/retail price
    resale_price    NUMERIC,                         -- Resale estimate
    source_urls     JSONB,                           -- Where prices came from
    sample_size     INTEGER DEFAULT 1,
    
    cached_at       TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL               -- TTL-based expiration
);

COMMENT ON TABLE price_cache IS 'Temporary websearch results. Can be cleared anytime.';

CREATE INDEX idx_price_cache_expires ON price_cache(expires_at);


-- -----------------------------------------------------------------------------
-- PRICE_HISTORY: Track auction price evolution
-- -----------------------------------------------------------------------------
-- Purpose: See how auction prices change over time
-- UI Use: Price chart on listing detail page
-- -----------------------------------------------------------------------------
CREATE TABLE price_history (
    id              BIGSERIAL PRIMARY KEY,
    listing_id      BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    
    price           NUMERIC NOT NULL,
    bids_count      INTEGER,
    observed_at     TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE price_history IS 'Price changes over time for auction listings.';

CREATE INDEX idx_price_history_listing ON price_history(listing_id, observed_at DESC);


-- =============================================================================
-- VIEWS (Convenience for common queries)
-- =============================================================================

-- Active deals with full context
CREATE OR REPLACE VIEW v_active_deals AS
SELECT 
    d.id AS deal_id,
    d.expected_profit,
    d.deal_score,
    d.strategy,
    d.strategy_reason,
    d.cost_estimate,
    d.market_value,
    d.price_source,
    d.is_bundle,
    d.evaluated_at,
    
    -- Product info
    p.display_name AS product_name,
    p.brand,
    p.category,
    
    -- Listing info
    l.title,
    l.url,
    l.image_url,
    l.buy_now_price,
    l.current_bid,
    l.bids_count,
    l.end_time,
    l.location,
    l.seller_rating,
    
    -- Computed
    EXTRACT(EPOCH FROM (l.end_time - NOW())) / 3600 AS hours_remaining,
    CASE WHEN l.end_time < NOW() + INTERVAL '24 hours' THEN TRUE ELSE FALSE END AS ending_soon
    
FROM deals d
JOIN listings l ON d.listing_id = l.id
LEFT JOIN products p ON d.product_id = p.id
WHERE d.status = 'active';

COMMENT ON VIEW v_active_deals IS 'All active deals with product and listing details. Use for dashboard.';


-- Top deals (profitable, sorted)
CREATE OR REPLACE VIEW v_top_deals AS
SELECT * FROM v_active_deals
WHERE expected_profit > 0
ORDER BY deal_score DESC, expected_profit DESC;

COMMENT ON VIEW v_top_deals IS 'Profitable deals sorted by score. Use for "Top Deals" widget.';


-- Deals requiring action
CREATE OR REPLACE VIEW v_action_required AS
SELECT * FROM v_active_deals
WHERE strategy IN ('buy_now', 'bid_now')
  AND (end_time IS NULL OR end_time > NOW())
ORDER BY 
    CASE strategy WHEN 'buy_now' THEN 1 WHEN 'bid_now' THEN 2 END,
    expected_profit DESC;

COMMENT ON VIEW v_action_required IS 'Deals that need immediate action. Use for notification/alerts.';


-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Get or create product by variant_key
CREATE OR REPLACE FUNCTION get_or_create_product(
    p_variant_key TEXT,
    p_display_name TEXT,
    p_brand TEXT DEFAULT NULL,
    p_category TEXT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_product_id INTEGER;
BEGIN
    -- Try to find existing
    SELECT id INTO v_product_id FROM products WHERE variant_key = p_variant_key;
    
    -- Create if not exists
    IF v_product_id IS NULL THEN
        INSERT INTO products (variant_key, display_name, brand, category)
        VALUES (p_variant_key, p_display_name, p_brand, p_category)
        RETURNING id INTO v_product_id;
    END IF;
    
    RETURN v_product_id;
END;
$$ LANGUAGE plpgsql;


-- Expire old deals (call periodically)
CREATE OR REPLACE FUNCTION expire_old_deals() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE deals 
    SET status = 'expired'
    WHERE status = 'active'
      AND expires_at IS NOT NULL
      AND expires_at < NOW();
    
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- Clean expired price cache
CREATE OR REPLACE FUNCTION clean_price_cache() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    DELETE FROM price_cache WHERE expires_at < NOW();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- SAMPLE QUERIES (for reference)
-- =============================================================================

-- Top 10 deals today by profit:
-- SELECT * FROM v_top_deals LIMIT 10;

-- All active deals for iPhone 12 mini:
-- SELECT * FROM v_active_deals WHERE product_name ILIKE '%iphone 12 mini%';

-- Average profit per product:
-- SELECT product_name, category, COUNT(*), AVG(expected_profit)
-- FROM v_active_deals GROUP BY product_name, category ORDER BY AVG(expected_profit) DESC;

-- Bundles vs singles:
-- SELECT is_bundle, COUNT(*), AVG(expected_profit) FROM v_active_deals GROUP BY is_bundle;

-- Buy now vs watch:
-- SELECT strategy, COUNT(*), AVG(expected_profit) FROM v_active_deals GROUP BY strategy;
