-- =============================================================================
-- DealFinder Schema v2.2 FINAL - Production-Grade
-- =============================================================================
-- Changes from v2.1:
--   1. USER_ACTIONS table for buy/watch/skip/purchased decisions
--   2. PRODUCT_ALIASES for variant_key evolution and migration
--   3. Data type consistency (UUID, TIMESTAMPTZ, NUMERIC(12,2))
--   4. Bundle model cleanup (no orphan fields)
--   5. Production-grade views with user action overlay
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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
    variant_key         TEXT NOT NULL UNIQUE,        -- Current canonical: "apple_iphone_12_mini_128gb_green"
    display_name        TEXT NOT NULL,               -- "Apple iPhone 12 mini 128GB Green"
    
    -- Classification
    brand               TEXT,
    category            TEXT,
    
    -- Reference pricing (updated from websearch)
    reference_price     NUMERIC(12,2),               -- Typical NEW price (CHF)
    resale_estimate     NUMERIC(12,2),               -- Typical RESALE price (CHF)
    price_updated       TIMESTAMPTZ,
    
    -- Metadata
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_reference_price CHECK (reference_price IS NULL OR reference_price >= 0),
    CONSTRAINT chk_resale_estimate CHECK (resale_estimate IS NULL OR resale_estimate >= 0)
);

COMMENT ON TABLE products IS 'Stable product identity with two-level hierarchy. variant_key is current canonical identifier.';
COMMENT ON COLUMN products.base_product_key IS 'Stable product family (e.g., apple_iphone_12_mini) - use for grouping';
COMMENT ON COLUMN products.variant_key IS 'Current canonical variant identifier - may evolve, see product_aliases';
COMMENT ON COLUMN products.reference_price IS 'Typical new/retail price in CHF';
COMMENT ON COLUMN products.resale_estimate IS 'Typical resale value in CHF';

CREATE UNIQUE INDEX idx_products_variant ON products(variant_key);
CREATE INDEX idx_products_base ON products(base_product_key);
CREATE INDEX idx_products_brand ON products(brand);
CREATE INDEX idx_products_category ON products(category);


-- -----------------------------------------------------------------------------
-- PRODUCT_ALIASES: Handle variant_key evolution and migration
-- -----------------------------------------------------------------------------
CREATE TABLE product_aliases (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    alias_key       TEXT NOT NULL UNIQUE,            -- Old or alternative variant_key
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE product_aliases IS 'Maps old/alternative variant_keys to canonical product. Handles AI extraction evolution.';
COMMENT ON COLUMN product_aliases.alias_key IS 'Historical or alternative variant_key that resolves to product_id';

CREATE INDEX idx_product_aliases_product ON product_aliases(product_id);
CREATE UNIQUE INDEX idx_product_aliases_key ON product_aliases(alias_key);


-- -----------------------------------------------------------------------------
-- LISTINGS: Raw marketplace facts
-- -----------------------------------------------------------------------------
CREATE TABLE listings (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              UUID NOT NULL,
    
    -- Source identity
    platform            TEXT NOT NULL DEFAULT 'ricardo',
    source_id           TEXT NOT NULL,
    url                 TEXT NOT NULL,
    
    -- Content
    title               TEXT NOT NULL,
    image_url           TEXT,
    
    -- Product link (resolved via variant_key or alias)
    product_id          INTEGER REFERENCES products(id),
    
    -- Pricing (what seller is asking)
    buy_now_price       NUMERIC(12,2),
    current_bid         NUMERIC(12,2),
    
    -- Auction state
    bids_count          INTEGER DEFAULT 0,
    end_time            TIMESTAMPTZ,
    
    -- Location & shipping
    location            TEXT,
    shipping_cost       NUMERIC(12,2),
    pickup_available    BOOLEAN DEFAULT FALSE,
    
    -- Seller
    seller_rating       INTEGER,
    
    -- Lifecycle tracking
    first_seen          TIMESTAMPTZ DEFAULT NOW(),
    last_seen           TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT uq_listing_source UNIQUE (platform, source_id),
    CONSTRAINT chk_buy_now_price CHECK (buy_now_price IS NULL OR buy_now_price >= 0),
    CONSTRAINT chk_current_bid CHECK (current_bid IS NULL OR current_bid >= 0),
    CONSTRAINT chk_shipping_cost CHECK (shipping_cost IS NULL OR shipping_cost >= 0),
    CONSTRAINT chk_bids_count CHECK (bids_count >= 0),
    CONSTRAINT chk_seller_rating CHECK (seller_rating IS NULL OR (seller_rating >= 0 AND seller_rating <= 100))
);

COMMENT ON TABLE listings IS 'Raw marketplace facts. One row per Ricardo listing.';
COMMENT ON COLUMN listings.first_seen IS 'When this listing was first discovered';
COMMENT ON COLUMN listings.last_seen IS 'When this listing was last seen in a run';
COMMENT ON COLUMN listings.seller_rating IS 'Seller trustworthiness percentage (0-100)';

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
    run_id              UUID NOT NULL,
    
    -- === EVALUATION ===
    cost_estimate       NUMERIC(12,2) NOT NULL,      -- What you'd pay
    market_value        NUMERIC(12,2) NOT NULL,      -- What you'd sell for
    expected_profit     NUMERIC(12,2) NOT NULL,      -- market_value - cost - fees
    
    deal_score          NUMERIC(3,1) NOT NULL,       -- 1.0 - 10.0 rating
    
    -- Action
    strategy            TEXT NOT NULL,               -- 'buy_now', 'bid_now', 'watch', 'skip'
    strategy_reason     TEXT,
    
    -- Timestamps
    evaluated_at        TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT uq_deal_listing_run UNIQUE (listing_id, run_id),
    CONSTRAINT valid_strategy CHECK (strategy IN ('buy_now', 'bid_now', 'watch', 'skip')),
    CONSTRAINT chk_cost_estimate CHECK (cost_estimate >= 0),
    CONSTRAINT chk_market_value CHECK (market_value >= 0),
    CONSTRAINT chk_deal_score CHECK (deal_score >= 1.0 AND deal_score <= 10.0)
);

COMMENT ON TABLE deals IS 'Immutable evaluations. One row per listing per run. Single products only.';
COMMENT ON COLUMN deals.cost_estimate IS 'What you would pay: buy_now or predicted final price';
COMMENT ON COLUMN deals.market_value IS 'What you could sell for: resale estimate';
COMMENT ON COLUMN deals.expected_profit IS 'market_value - cost_estimate - fees (can be negative)';
COMMENT ON COLUMN deals.deal_score IS 'Rating from 1.0 to 10.0';

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
    run_id              UUID NOT NULL,
    
    -- === BUNDLE EVALUATION ===
    total_cost          NUMERIC(12,2) NOT NULL,
    total_value         NUMERIC(12,2) NOT NULL,
    expected_profit     NUMERIC(12,2) NOT NULL,
    
    deal_score          NUMERIC(3,1),
    
    -- Action
    strategy            TEXT,
    strategy_reason     TEXT,
    
    -- Timestamps
    evaluated_at        TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT uq_bundle_listing_run UNIQUE (listing_id, run_id),
    CONSTRAINT valid_bundle_strategy CHECK (strategy IN ('buy_now', 'bid_now', 'watch', 'skip')),
    CONSTRAINT chk_total_cost CHECK (total_cost >= 0),
    CONSTRAINT chk_total_value CHECK (total_value >= 0),
    CONSTRAINT chk_bundle_score CHECK (deal_score IS NULL OR (deal_score >= 1.0 AND deal_score <= 10.0))
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
    
    -- Parent bundle (NOT deals - bundles are separate)
    bundle_id       INTEGER NOT NULL REFERENCES bundles(id) ON DELETE CASCADE,
    
    -- Component
    product_id      INTEGER REFERENCES products(id),
    product_name    TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    
    -- Per-item pricing
    unit_value      NUMERIC(12,2),
    
    -- Constraints
    CONSTRAINT chk_quantity CHECK (quantity >= 1),
    CONSTRAINT chk_unit_value CHECK (unit_value IS NULL OR unit_value >= 0)
);

COMMENT ON TABLE bundle_items IS 'Components of a bundle with quantities and per-item values.';
COMMENT ON COLUMN bundle_items.bundle_id IS 'References bundles.id (NOT deals - bundles are separate entities)';

CREATE INDEX idx_bundle_items_bundle ON bundle_items(bundle_id);
CREATE INDEX idx_bundle_items_product ON bundle_items(product_id);


-- -----------------------------------------------------------------------------
-- USER_ACTIONS: User decisions independent of run snapshots
-- -----------------------------------------------------------------------------
CREATE TABLE user_actions (
    id              BIGSERIAL PRIMARY KEY,
    
    -- Target (prefer listing_id for stability across runs)
    listing_id      BIGINT REFERENCES listings(id) ON DELETE CASCADE,
    product_id      INTEGER REFERENCES products(id),
    
    -- User decision
    action          TEXT NOT NULL,                   -- 'buy', 'watch', 'ignore', 'purchased', 'archived'
    notes           TEXT,
    tags            TEXT[],                          -- Array of tags for filtering
    
    -- Timestamps
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_user_action CHECK (action IN ('buy', 'watch', 'ignore', 'purchased', 'archived')),
    CONSTRAINT chk_has_target CHECK (listing_id IS NOT NULL OR product_id IS NOT NULL)
);

COMMENT ON TABLE user_actions IS 'User decisions independent of run snapshots. Overlays on top of deals/bundles.';
COMMENT ON COLUMN user_actions.listing_id IS 'Preferred: attach to specific listing (stable across runs)';
COMMENT ON COLUMN user_actions.product_id IS 'Optional: attach to product (applies to all listings of this product)';
COMMENT ON COLUMN user_actions.action IS 'User decision: buy, watch, ignore, purchased, archived';
COMMENT ON COLUMN user_actions.tags IS 'Array of user-defined tags for filtering';

CREATE INDEX idx_user_actions_listing ON user_actions(listing_id);
CREATE INDEX idx_user_actions_product ON user_actions(product_id);
CREATE INDEX idx_user_actions_action ON user_actions(action);
CREATE INDEX idx_user_actions_tags ON user_actions USING GIN(tags);


-- =============================================================================
-- OPERATIONAL TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- RUNS: Pipeline execution metadata
-- -----------------------------------------------------------------------------
CREATE TABLE runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Timing
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
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
    ai_cost_usd     NUMERIC(10,4) DEFAULT 0,
    websearch_calls INTEGER DEFAULT 0,
    
    -- Status
    status          TEXT DEFAULT 'running',
    error_message   TEXT,
    
    -- Constraints
    CONSTRAINT chk_mode CHECK (mode IN ('test', 'prod')),
    CONSTRAINT chk_run_status CHECK (status IN ('running', 'completed', 'failed')),
    CONSTRAINT chk_duration CHECK (duration_sec IS NULL OR duration_sec >= 0),
    CONSTRAINT chk_counts CHECK (
        listings_found >= 0 AND 
        deals_created >= 0 AND 
        bundles_created >= 0 AND 
        profitable_deals >= 0
    ),
    CONSTRAINT chk_ai_cost CHECK (ai_cost_usd >= 0),
    CONSTRAINT chk_websearch_calls CHECK (websearch_calls >= 0)
);

COMMENT ON TABLE runs IS 'Pipeline execution metadata. One row per run.';

CREATE INDEX idx_runs_started ON runs(started_at DESC);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_mode ON runs(mode);


-- -----------------------------------------------------------------------------
-- DEAL_AUDIT: Pipeline metadata for deals
-- -----------------------------------------------------------------------------
CREATE TABLE deal_audit (
    deal_id         BIGINT PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
    
    -- Price source
    price_source    TEXT NOT NULL,
    
    -- Pipeline metadata
    ai_cost_usd     NUMERIC(10,4),
    cache_hit       BOOLEAN DEFAULT FALSE,
    web_search_used BOOLEAN DEFAULT FALSE,
    vision_used     BOOLEAN DEFAULT FALSE,
    
    -- Timestamp
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_price_source CHECK (price_source IN (
        'web_median', 'web_single', 'web_median_qty_adjusted',
        'ai_estimate', 'query_baseline', 'buy_now_fallback',
        'bundle_aggregate', 'market_auction', 'no_price'
    )),
    CONSTRAINT chk_audit_ai_cost CHECK (ai_cost_usd IS NULL OR ai_cost_usd >= 0)
);

COMMENT ON TABLE deal_audit IS 'Pipeline metadata for deals. Separated from business data.';

CREATE INDEX idx_deal_audit_price_source ON deal_audit(price_source);


-- -----------------------------------------------------------------------------
-- BUNDLE_AUDIT: Pipeline metadata for bundles
-- -----------------------------------------------------------------------------
CREATE TABLE bundle_audit (
    bundle_id       INTEGER PRIMARY KEY REFERENCES bundles(id) ON DELETE CASCADE,
    
    price_source    TEXT NOT NULL,
    ai_cost_usd     NUMERIC(10,4),
    cache_hit       BOOLEAN DEFAULT FALSE,
    web_search_used BOOLEAN DEFAULT FALSE,
    
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_bundle_audit_ai_cost CHECK (ai_cost_usd IS NULL OR ai_cost_usd >= 0)
);

COMMENT ON TABLE bundle_audit IS 'Pipeline metadata for bundles.';


-- -----------------------------------------------------------------------------
-- PRICE_CACHE: Temporary websearch results
-- -----------------------------------------------------------------------------
CREATE TABLE price_cache (
    variant_key     TEXT PRIMARY KEY,
    
    new_price       NUMERIC(12,2),
    resale_price    NUMERIC(12,2),
    source_urls     JSONB,
    sample_size     INTEGER DEFAULT 1,
    
    cached_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    
    -- Constraints
    CONSTRAINT chk_cache_new_price CHECK (new_price IS NULL OR new_price >= 0),
    CONSTRAINT chk_cache_resale_price CHECK (resale_price IS NULL OR resale_price >= 0),
    CONSTRAINT chk_cache_sample_size CHECK (sample_size >= 0)
);

COMMENT ON TABLE price_cache IS 'Temporary websearch results. Can be cleared anytime.';

CREATE INDEX idx_price_cache_expires ON price_cache(expires_at);


-- -----------------------------------------------------------------------------
-- PRICE_HISTORY: Track auction price evolution
-- -----------------------------------------------------------------------------
CREATE TABLE price_history (
    id              BIGSERIAL PRIMARY KEY,
    listing_id      BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    
    price           NUMERIC(12,2) NOT NULL,
    bids_count      INTEGER,
    observed_at     TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_history_price CHECK (price >= 0),
    CONSTRAINT chk_history_bids CHECK (bids_count IS NULL OR bids_count >= 0)
);

COMMENT ON TABLE price_history IS 'Price changes over time for auction listings.';

CREATE INDEX idx_price_history_listing ON price_history(listing_id, observed_at DESC);


-- =============================================================================
-- VIEWS (Production-Grade with User Action Overlay)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- v_latest_deals: All deals from latest run with full context
-- -----------------------------------------------------------------------------
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
    p.id AS product_id,
    p.display_name AS product_name,
    p.base_product_key,
    p.brand,
    p.category,
    
    -- Listing info
    l.id AS listing_id,
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
    
    -- User action overlay (NULL if no action)
    ua.action AS user_action,
    ua.notes AS user_notes,
    ua.tags AS user_tags,
    ua.updated_at AS user_action_date,
    
    -- Computed
    EXTRACT(EPOCH FROM (l.end_time - NOW())) / 3600 AS hours_remaining,
    CASE WHEN l.end_time < NOW() + INTERVAL '24 hours' THEN TRUE ELSE FALSE END AS ending_soon,
    CASE WHEN d.cost_estimate > 0 THEN (d.expected_profit / d.cost_estimate) * 100 ELSE NULL END AS profit_margin_pct,
    
    -- Run info
    d.run_id,
    d.evaluated_at
    
FROM deals d
JOIN listings l ON d.listing_id = l.id
LEFT JOIN products p ON d.product_id = p.id
LEFT JOIN deal_audit da ON d.id = da.deal_id
LEFT JOIN user_actions ua ON l.id = ua.listing_id
WHERE d.run_id = (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1);

COMMENT ON VIEW v_latest_deals IS 'All deals from most recent run with user action overlay. Use for dashboard.';


-- -----------------------------------------------------------------------------
-- v_latest_bundles: All bundles from latest run
-- -----------------------------------------------------------------------------
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
    l.id AS listing_id,
    l.title,
    l.url,
    l.image_url,
    l.end_time,
    l.location,
    l.seller_rating,
    
    -- User action overlay
    ua.action AS user_action,
    ua.notes AS user_notes,
    ua.tags AS user_tags,
    
    -- Component count
    (SELECT COUNT(*) FROM bundle_items WHERE bundle_id = b.id) AS item_count,
    
    -- Computed
    EXTRACT(EPOCH FROM (l.end_time - NOW())) / 3600 AS hours_remaining,
    CASE WHEN b.total_cost > 0 THEN (b.expected_profit / b.total_cost) * 100 ELSE NULL END AS profit_margin_pct,
    
    -- Run info
    b.run_id,
    b.evaluated_at
    
FROM bundles b
JOIN listings l ON b.listing_id = l.id
LEFT JOIN user_actions ua ON l.id = ua.listing_id
WHERE b.run_id = (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1);

COMMENT ON VIEW v_latest_bundles IS 'All bundles from most recent run with user action overlay.';


-- -----------------------------------------------------------------------------
-- v_dashboard: Combined deals + bundles for main UI
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_dashboard AS
-- Deals
SELECT 
    'deal' AS type,
    deal_id AS id,
    product_name AS name,
    expected_profit,
    deal_score,
    strategy,
    cost_estimate AS cost,
    market_value AS value,
    listing_id,
    url,
    image_url,
    end_time,
    hours_remaining,
    ending_soon,
    user_action,
    user_notes,
    user_tags,
    profit_margin_pct,
    evaluated_at
FROM v_latest_deals

UNION ALL

-- Bundles
SELECT 
    'bundle' AS type,
    bundle_id AS id,
    title AS name,
    expected_profit,
    deal_score,
    strategy,
    total_cost AS cost,
    total_value AS value,
    listing_id,
    url,
    image_url,
    end_time,
    hours_remaining,
    FALSE AS ending_soon,
    user_action,
    user_notes,
    user_tags,
    profit_margin_pct,
    evaluated_at
FROM v_latest_bundles

ORDER BY deal_score DESC NULLS LAST, expected_profit DESC;

COMMENT ON VIEW v_dashboard IS 'Unified view of deals + bundles for main dashboard. Sorted by score and profit.';


-- -----------------------------------------------------------------------------
-- v_action_required: Items needing immediate action
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_action_required AS
SELECT * FROM v_dashboard
WHERE strategy IN ('buy_now', 'bid_now')
  AND (end_time IS NULL OR end_time > NOW())
  AND (user_action IS NULL OR user_action NOT IN ('purchased', 'archived', 'ignore'))
ORDER BY 
    CASE strategy WHEN 'buy_now' THEN 1 WHEN 'bid_now' THEN 2 END,
    expected_profit DESC;

COMMENT ON VIEW v_action_required IS 'Deals/bundles requiring immediate action, excluding already handled items.';


-- -----------------------------------------------------------------------------
-- v_watchlist: Items marked for watching
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_watchlist AS
SELECT * FROM v_dashboard
WHERE user_action = 'watch'
  AND (end_time IS NULL OR end_time > NOW())
ORDER BY end_time ASC NULLS LAST;

COMMENT ON VIEW v_watchlist IS 'Items user is actively watching.';


-- -----------------------------------------------------------------------------
-- v_purchased: Items user has purchased
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_purchased AS
SELECT 
    d.*,
    ua.created_at AS purchase_date,
    ua.notes AS purchase_notes
FROM v_dashboard d
JOIN user_actions ua ON d.listing_id = ua.listing_id
WHERE ua.action = 'purchased'
ORDER BY ua.created_at DESC;

COMMENT ON VIEW v_purchased IS 'Items user has marked as purchased.';


-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Get or create product with hierarchy and alias support
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
    -- Try to find by canonical variant_key
    SELECT id INTO v_product_id FROM products WHERE variant_key = p_variant_key;
    
    -- Try to find by alias
    IF v_product_id IS NULL THEN
        SELECT product_id INTO v_product_id FROM product_aliases WHERE alias_key = p_variant_key;
    END IF;
    
    -- Create if not exists
    IF v_product_id IS NULL THEN
        INSERT INTO products (base_product_key, variant_key, display_name, brand, category)
        VALUES (p_base_product_key, p_variant_key, p_display_name, p_brand, p_category)
        RETURNING id INTO v_product_id;
    END IF;
    
    RETURN v_product_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_or_create_product IS 'Get or create product, checking both variant_key and aliases.';


-- Resolve variant_key to product_id (handles aliases)
CREATE OR REPLACE FUNCTION resolve_product(p_variant_key TEXT) RETURNS INTEGER AS $$
DECLARE
    v_product_id INTEGER;
BEGIN
    -- Try canonical variant_key
    SELECT id INTO v_product_id FROM products WHERE variant_key = p_variant_key;
    
    -- Try alias
    IF v_product_id IS NULL THEN
        SELECT product_id INTO v_product_id FROM product_aliases WHERE alias_key = p_variant_key;
    END IF;
    
    RETURN v_product_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION resolve_product IS 'Resolve variant_key to product_id, checking aliases.';


-- Add product alias (for variant_key migration)
CREATE OR REPLACE FUNCTION add_product_alias(
    p_product_id INTEGER,
    p_alias_key TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO product_aliases (product_id, alias_key)
    VALUES (p_product_id, p_alias_key)
    ON CONFLICT (alias_key) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION add_product_alias IS 'Add an alias for a product (e.g., old variant_key after normalization change).';


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
CREATE OR REPLACE FUNCTION get_latest_run_id() RETURNS UUID AS $$
BEGIN
    RETURN (SELECT id FROM runs ORDER BY started_at DESC LIMIT 1);
END;
$$ LANGUAGE plpgsql;


-- Set user action (upsert)
CREATE OR REPLACE FUNCTION set_user_action(
    p_listing_id BIGINT,
    p_action TEXT,
    p_notes TEXT DEFAULT NULL,
    p_tags TEXT[] DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    INSERT INTO user_actions (listing_id, action, notes, tags)
    VALUES (p_listing_id, p_action, p_notes, p_tags)
    ON CONFLICT (listing_id) 
    DO UPDATE SET 
        action = EXCLUDED.action,
        notes = EXCLUDED.notes,
        tags = EXCLUDED.tags,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_user_action IS 'Set or update user action for a listing.';


-- =============================================================================
-- SAMPLE QUERIES (for reference)
-- =============================================================================

-- Top 10 deals with user action overlay:
-- SELECT * FROM v_latest_deals WHERE expected_profit > 0 ORDER BY deal_score DESC LIMIT 10;

-- All deals for a product family:
-- SELECT * FROM v_latest_deals WHERE base_product_key = 'apple_iphone_12_mini';

-- Items requiring action (not yet handled):
-- SELECT * FROM v_action_required;

-- Purchased items list:
-- SELECT * FROM v_purchased;

-- Watchlist:
-- SELECT * FROM v_watchlist;

-- Mark listing as purchased:
-- SELECT set_user_action(123, 'purchased', 'Bought for 50 CHF on Ricardo');

-- Add product alias (after variant_key normalization change):
-- SELECT add_product_alias(42, 'apple_iphone_12_mini_128GB');  -- Old format
-- -- Now both 'apple_iphone_12_mini_128gb' and 'apple_iphone_12_mini_128GB' resolve to product 42

-- Product performance over time:
-- SELECT p.display_name, d.run_id, AVG(d.expected_profit), COUNT(*)
-- FROM deals d JOIN products p ON d.product_id = p.id
-- GROUP BY p.display_name, d.run_id ORDER BY p.display_name, d.run_id DESC;

-- Compare runs:
-- SELECT 
--     r.id AS run_id,
--     r.started_at,
--     r.deals_created,
--     r.profitable_deals,
--     r.ai_cost_usd
-- FROM runs r
-- ORDER BY r.started_at DESC
-- LIMIT 10;
