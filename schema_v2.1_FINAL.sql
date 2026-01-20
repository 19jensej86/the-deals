-- =============================================================================
-- DealFinder Schema v2.1 FINAL - Critical Review Applied
-- =============================================================================
-- Key Changes from v2.0:
--   1. Deals are IMMUTABLE SNAPSHOTS (removed status, expires_at)
--   2. Products have STABLE HIERARCHY (base_product_key)
--   3. Bundles are FIRST-CLASS ENTITIES (separate from deals)
--   4. Audit data SEPARATED (deal_audit table)
-- =============================================================================

-- =============================================================================
-- CORE BUSINESS TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- PRODUCTS: Stable product identity with hierarchy
-- -----------------------------------------------------------------------------
CREATE TABLE products (
    id                  SERIAL PRIMARY KEY,
    
    -- Identity (two-level hierarchy)
    base_product_key    TEXT NOT NULL,               -- Stable: "apple_iphone_12_mini"
    variant_key         TEXT NOT NULL UNIQUE,        -- Specific: "apple_iphone_12_mini_128gb_green"
    display_name        TEXT NOT NULL,               -- "Apple iPhone 12 mini 128GB Green"
    
    -- Classification
    brand               TEXT,                        -- "Apple"
    category            TEXT,                        -- "smartphone"
    
    -- Reference pricing (updated from websearch)
    reference_price     NUMERIC,                     -- Typical NEW price (CHF)
    resale_estimate     NUMERIC,                     -- Typical RESALE price (CHF)
    price_updated       TIMESTAMP,
    
    -- Metadata
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE products IS 'Stable product identity with two-level hierarchy for variant grouping.';
COMMENT ON COLUMN products.base_product_key IS 'Stable product family identifier (e.g., apple_iphone_12_mini)';
COMMENT ON COLUMN products.variant_key IS 'Specific variant with storage/color (e.g., apple_iphone_12_mini_128gb_green)';

CREATE UNIQUE INDEX idx_products_variant ON products(variant_key);
CREATE INDEX idx_products_base ON products(base_product_key);
CREATE INDEX idx_products_brand ON products(brand);
CREATE INDEX idx_products_category ON products(category);


-- -----------------------------------------------------------------------------
-- LISTINGS: Raw marketplace facts
-- -----------------------------------------------------------------------------
CREATE TABLE listings (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    
    -- Source identity
    platform            TEXT NOT NULL DEFAULT 'ricardo',
    source_id           TEXT NOT NULL,               -- Ricardo listing ID
    url                 TEXT NOT NULL,
    
    -- Content
    title               TEXT NOT NULL,
    image_url           TEXT,
    
    -- Product link
    product_id          INTEGER REFERENCES products(id),
    
    -- Pricing (what seller is asking)
    buy_now_price       NUMERIC,
    current_bid         NUMERIC,
    
    -- Auction state
    bids_count          INTEGER DEFAULT 0,
    end_time            TIMESTAMP,
    
    -- Location & shipping
    location            TEXT,
    shipping_cost       NUMERIC,
    pickup_available    BOOLEAN DEFAULT FALSE,
    
    -- Seller
    seller_rating       INTEGER,
    
    -- Lifecycle tracking
    first_seen          TIMESTAMP DEFAULT NOW(),
    last_seen           TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT uq_listing_source UNIQUE (platform, source_id)
);

COMMENT ON TABLE listings IS 'Raw marketplace facts. One row per Ricardo listing.';
COMMENT ON COLUMN listings.first_seen IS 'When this listing was first discovered';
COMMENT ON COLUMN listings.last_seen IS 'When this listing was last seen in a run';

CREATE INDEX idx_listings_run ON listings(run_id);
CREATE INDEX idx_listings_product ON listings(product_id);
CREATE INDEX idx_listings_end_time ON listings(end_time) WHERE end_time IS NOT NULL;
CREATE INDEX idx_listings_platform_source ON listings(platform, source_id);


-- -----------------------------------------------------------------------------
-- DEALS: Immutable point-in-time evaluations (SINGLE PRODUCTS ONLY)
-- -----------------------------------------------------------------------------
CREATE TABLE deals (
    id                  BIGSERIAL PRIMARY KEY,
    
    -- Links
    listing_id          BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    product_id          INTEGER REFERENCES products(id),
    run_id              TEXT NOT NULL,
    
    -- === EVALUATION (The Important Stuff) ===
    cost_estimate       NUMERIC NOT NULL,            -- What you'd pay
    market_value        NUMERIC NOT NULL,            -- What you'd sell for
    expected_profit     NUMERIC NOT NULL,            -- market_value - cost - fees
    
    deal_score          NUMERIC NOT NULL,            -- 1-10 rating
    
    -- Action
    strategy            TEXT NOT NULL,               -- 'buy_now', 'bid_now', 'watch', 'skip'
    strategy_reason     TEXT,                        -- Human explanation
    
    -- Timestamps
    evaluated_at        TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT uq_deal_listing_run UNIQUE (listing_id, run_id),
    CONSTRAINT valid_strategy CHECK (strategy IN ('buy_now', 'bid_now', 'watch', 'skip'))
);

COMMENT ON TABLE deals IS 'Immutable evaluations. One row per listing per run. Single products only.';
COMMENT ON COLUMN deals.cost_estimate IS 'What you would pay: buy_now or predicted final price';
COMMENT ON COLUMN deals.market_value IS 'What you could sell for: resale estimate';
COMMENT ON COLUMN deals.expected_profit IS 'market_value - cost_estimate - fees';

CREATE INDEX idx_deals_run ON deals(run_id);
CREATE INDEX idx_deals_score ON deals(deal_score DESC);
CREATE INDEX idx_deals_profit ON deals(expected_profit DESC);
CREATE INDEX idx_deals_strategy ON deals(strategy);
CREATE INDEX idx_deals_product ON deals(product_id);
CREATE INDEX idx_deals_listing ON deals(listing_id);


-- -----------------------------------------------------------------------------
-- BUNDLES: First-class bundle entities (SEPARATE FROM DEALS)
-- -----------------------------------------------------------------------------
CREATE TABLE bundles (
    id                  SERIAL PRIMARY KEY,
    
    -- Links
    listing_id          BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    run_id              TEXT NOT NULL,
    
    -- === BUNDLE EVALUATION ===
    total_cost          NUMERIC NOT NULL,            -- Total cost for entire bundle
    total_value         NUMERIC NOT NULL,            -- Total resale value
    expected_profit     NUMERIC NOT NULL,            -- total_value - total_cost - fees
    
    deal_score          NUMERIC,
    
    -- Action
    strategy            TEXT,
    strategy_reason     TEXT,
    
    -- Timestamps
    evaluated_at        TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT uq_bundle_listing_run UNIQUE (listing_id, run_id),
    CONSTRAINT valid_bundle_strategy CHECK (strategy IN ('buy_now', 'bid_now', 'watch', 'skip'))
);

COMMENT ON TABLE bundles IS 'Bundle evaluations. Separate from single-product deals.';
COMMENT ON COLUMN bundles.total_cost IS 'Total cost for entire bundle';
COMMENT ON COLUMN bundles.total_value IS 'Sum of all component resale values';

CREATE INDEX idx_bundles_run ON bundles(run_id);
CREATE INDEX idx_bundles_score ON bundles(deal_score DESC);
CREATE INDEX idx_bundles_profit ON bundles(expected_profit DESC);
CREATE INDEX idx_bundles_listing ON bundles(listing_id);


-- -----------------------------------------------------------------------------
-- BUNDLE_ITEMS: Components of a bundle
-- -----------------------------------------------------------------------------
CREATE TABLE bundle_items (
    id              SERIAL PRIMARY KEY,
    
    -- Parent bundle
    bundle_id       INTEGER NOT NULL REFERENCES bundles(id) ON DELETE CASCADE,
    
    -- Component
    product_id      INTEGER REFERENCES products(id),
    product_name    TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    
    -- Per-item pricing
    unit_value      NUMERIC,
    
    CONSTRAINT valid_quantity CHECK (quantity >= 1)
);

COMMENT ON TABLE bundle_items IS 'Components of a bundle with quantities and per-item values.';

CREATE INDEX idx_bundle_items_bundle ON bundle_items(bundle_id);
CREATE INDEX idx_bundle_items_product ON bundle_items(product_id);


-- =============================================================================
-- OPERATIONAL TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- RUNS: Pipeline execution metadata
-- -----------------------------------------------------------------------------
CREATE TABLE runs (
    id              TEXT PRIMARY KEY,
    
    -- Timing
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP,
    duration_sec    INTEGER,
    
    -- Configuration
    mode            TEXT NOT NULL,
    queries         JSONB,
    
    -- Results
    listings_found  INTEGER DEFAULT 0,
    deals_created   INTEGER DEFAULT 0,
    bundles_created INTEGER DEFAULT 0,
    profitable_deals INTEGER DEFAULT 0,
    
    -- Cost
    ai_cost_usd     NUMERIC DEFAULT 0,
    websearch_calls INTEGER DEFAULT 0,
    
    -- Status
    status          TEXT DEFAULT 'running',
    error_message   TEXT,
    
    CONSTRAINT valid_mode CHECK (mode IN ('test', 'prod')),
    CONSTRAINT valid_run_status CHECK (status IN ('running', 'completed', 'failed'))
);

COMMENT ON TABLE runs IS 'Pipeline execution metadata. One row per run.';

CREATE INDEX idx_runs_started ON runs(started_at DESC);
CREATE INDEX idx_runs_status ON runs(status);


-- -----------------------------------------------------------------------------
-- DEAL_AUDIT: Pipeline metadata for deals (separated from business data)
-- -----------------------------------------------------------------------------
CREATE TABLE deal_audit (
    deal_id         BIGINT PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
    
    -- Price source
    price_source    TEXT NOT NULL,
    
    -- Pipeline metadata
    ai_cost_usd     NUMERIC,
    cache_hit       BOOLEAN DEFAULT FALSE,
    web_search_used BOOLEAN DEFAULT FALSE,
    vision_used     BOOLEAN DEFAULT FALSE,
    
    -- Timestamp
    created_at      TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT valid_price_source CHECK (price_source IN (
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    ))
);

COMMENT ON TABLE deal_audit IS 'Pipeline metadata for deals. Separated from business data.';

CREATE INDEX idx_deal_audit_price_source ON deal_audit(price_source);


-- -----------------------------------------------------------------------------
-- BUNDLE_AUDIT: Pipeline metadata for bundles
-- -----------------------------------------------------------------------------
CREATE TABLE bundle_audit (
    bundle_id       INTEGER PRIMARY KEY REFERENCES bundles(id) ON DELETE CASCADE,
    
    price_source    TEXT NOT NULL,
    ai_cost_usd     NUMERIC,
    cache_hit       BOOLEAN DEFAULT FALSE,
    web_search_used BOOLEAN DEFAULT FALSE,
    
    created_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE bundle_audit IS 'Pipeline metadata for bundles.';


-- -----------------------------------------------------------------------------
-- PRICE_CACHE: Temporary websearch results
-- -----------------------------------------------------------------------------
CREATE TABLE price_cache (
    variant_key     TEXT PRIMARY KEY,
    
    new_price       NUMERIC,
    resale_price    NUMERIC,
    source_urls     JSONB,
    sample_size     INTEGER DEFAULT 1,
    
    cached_at       TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL
);

COMMENT ON TABLE price_cache IS 'Temporary websearch results. Can be cleared anytime.';

CREATE INDEX idx_price_cache_expires ON price_cache(expires_at);


-- -----------------------------------------------------------------------------
-- PRICE_HISTORY: Track auction price evolution
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

-- Active deals from latest run
CREATE OR REPLACE VIEW v_latest_deals AS
SELECT 
    d.id AS deal_id,
    d.expected_profit,
    d.deal_score,
    d.strategy,
    d.strategy_reason,
    d.cost_estimate,
    d.market_value,
    
    -- Product info
    p.display_name AS product_name,
    p.base_product_key,
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
    
    -- Audit info
    da.price_source,
    
    -- Computed
    EXTRACT(EPOCH FROM (l.end_time - NOW())) / 3600 AS hours_remaining,
    CASE WHEN l.end_time < NOW() + INTERVAL '24 hours' THEN TRUE ELSE FALSE END AS ending_soon,
    (d.expected_profit / NULLIF(d.cost_estimate, 0)) * 100 AS profit_margin_pct
    
FROM deals d
JOIN listings l ON d.listing_id = l.id
LEFT JOIN products p ON d.product_id = p.id
LEFT JOIN deal_audit da ON d.id = da.deal_id
WHERE d.run_id = (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1);

COMMENT ON VIEW v_latest_deals IS 'All deals from the most recent run with full context.';


-- Latest bundles
CREATE OR REPLACE VIEW v_latest_bundles AS
SELECT 
    b.id AS bundle_id,
    b.expected_profit,
    b.deal_score,
    b.strategy,
    b.strategy_reason,
    b.total_cost,
    b.total_value,
    
    -- Listing info
    l.title,
    l.url,
    l.image_url,
    l.end_time,
    l.location,
    
    -- Component count
    (SELECT COUNT(*) FROM bundle_items WHERE bundle_id = b.id) AS item_count,
    
    -- Computed
    EXTRACT(EPOCH FROM (l.end_time - NOW())) / 3600 AS hours_remaining
    
FROM bundles b
JOIN listings l ON b.listing_id = l.id
WHERE b.run_id = (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1);

COMMENT ON VIEW v_latest_bundles IS 'All bundles from the most recent run.';


-- Top profitable deals (latest run)
CREATE OR REPLACE VIEW v_top_deals AS
SELECT * FROM v_latest_deals
WHERE expected_profit > 0
ORDER BY deal_score DESC, expected_profit DESC;

COMMENT ON VIEW v_top_deals IS 'Profitable deals from latest run, sorted by score.';


-- Action required (buy_now or bid_now)
CREATE OR REPLACE VIEW v_action_required AS
SELECT * FROM v_latest_deals
WHERE strategy IN ('buy_now', 'bid_now')
  AND (end_time IS NULL OR end_time > NOW())
ORDER BY 
    CASE strategy WHEN 'buy_now' THEN 1 WHEN 'bid_now' THEN 2 END,
    expected_profit DESC;

COMMENT ON VIEW v_action_required IS 'Deals requiring immediate action from latest run.';


-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Get or create product with hierarchy
CREATE OR REPLACE FUNCTION get_or_create_product(
    p_base_product_key TEXT,
    p_variant_key TEXT,
    p_display_name TEXT,
    p_brand TEXT DEFAULT NULL,
    p_category TEXT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_product_id INTEGER;
BEGIN
    -- Try to find existing by variant_key
    SELECT id INTO v_product_id FROM products WHERE variant_key = p_variant_key;
    
    -- Create if not exists
    IF v_product_id IS NULL THEN
        INSERT INTO products (base_product_key, variant_key, display_name, brand, category)
        VALUES (p_base_product_key, p_variant_key, p_display_name, p_brand, p_category)
        RETURNING id INTO v_product_id;
    END IF;
    
    RETURN v_product_id;
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


-- Get latest run ID
CREATE OR REPLACE FUNCTION get_latest_run_id() RETURNS TEXT AS $$
BEGIN
    RETURN (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1);
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- SAMPLE QUERIES (for reference)
-- =============================================================================

-- Top 10 deals from latest run:
-- SELECT * FROM v_top_deals LIMIT 10;

-- All deals for a product family:
-- SELECT * FROM v_latest_deals WHERE base_product_key = 'apple_iphone_12_mini';

-- Compare deal performance across runs:
-- SELECT run_id, COUNT(*), AVG(expected_profit), SUM(CASE WHEN expected_profit > 0 THEN 1 ELSE 0 END)
-- FROM deals GROUP BY run_id ORDER BY run_id DESC;

-- Bundle vs single-product performance:
-- SELECT 'Deals' AS type, COUNT(*), AVG(expected_profit) FROM v_latest_deals
-- UNION ALL
-- SELECT 'Bundles', COUNT(*), AVG(expected_profit) FROM v_latest_bundles;

-- Product performance over time:
-- SELECT p.display_name, d.run_id, AVG(d.expected_profit), COUNT(*)
-- FROM deals d JOIN products p ON d.product_id = p.id
-- GROUP BY p.display_name, d.run_id ORDER BY p.display_name, d.run_id DESC;
