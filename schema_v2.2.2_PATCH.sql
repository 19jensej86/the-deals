-- =============================================================================
-- Schema v2.2.2 PATCH - Hardening (Final)
-- =============================================================================
-- Apply this patch AFTER creating schema_v2.2_FINAL.sql
-- 
-- Issues Fixed:
--   1. user_actions: Missing UNIQUE constraint for UPSERT
--   2. user_actions: listing_id allows NULL (UNIQUE allows multiple NULLs)
--   3. product_aliases: Weak normalization (GB vs gb, special chars, multiple underscores)
-- 
-- Changes from v2.2.1:
--   - Enforce user_actions.listing_id NOT NULL (listing-scoped only)
--   - Strengthen normalization: remove non-alphanumeric, collapse underscores
-- =============================================================================

-- -----------------------------------------------------------------------------
-- FIX 1: user_actions UNIQUE constraint + NOT NULL enforcement
-- -----------------------------------------------------------------------------
-- Problem 1: set_user_action() uses ON CONFLICT (listing_id), but no UNIQUE constraint.
-- Problem 2: listing_id allows NULL, and UNIQUE constraint allows multiple NULL rows.
-- Solution: Make listing_id NOT NULL and add UNIQUE constraint.

-- Step 1: Remove product_id support (simplify to listing-scoped only)
-- If product-level actions are needed later, create separate table.
ALTER TABLE user_actions 
    DROP COLUMN IF EXISTS product_id;

-- Step 2: Enforce listing_id NOT NULL
ALTER TABLE user_actions 
    ALTER COLUMN listing_id SET NOT NULL;

-- Step 3: Add UNIQUE constraint (skip if already exists)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'uq_user_actions_listing' 
        AND conrelid = 'user_actions'::regclass
    ) THEN
        ALTER TABLE user_actions 
            ADD CONSTRAINT uq_user_actions_listing UNIQUE (listing_id);
    END IF;
END $$;

-- Update constraint check (no longer need product_id check)
ALTER TABLE user_actions 
    DROP CONSTRAINT IF EXISTS chk_has_target;

-- Update comments
COMMENT ON TABLE user_actions IS 
    'User decisions independent of run snapshots. One action per listing.';
COMMENT ON COLUMN user_actions.listing_id IS 
    'Listing this action applies to. NOT NULL, UNIQUE (one action per listing).';


-- -----------------------------------------------------------------------------
-- FIX 2: Strengthen alias normalization
-- -----------------------------------------------------------------------------
-- Normalization rules:
--   1. Lowercase
--   2. Trim whitespace
--   3. Replace whitespace with underscores
--   4. Remove non [a-z0-9_] characters
--   5. Collapse multiple underscores to single underscore
--   6. Trim leading/trailing underscores

CREATE OR REPLACE FUNCTION normalize_variant_key(p_key TEXT) RETURNS TEXT AS $$
DECLARE
    v_normalized TEXT;
BEGIN
    -- Step 1: Lowercase and trim
    v_normalized := LOWER(TRIM(p_key));
    
    -- Step 2: Replace whitespace with underscores
    v_normalized := REGEXP_REPLACE(v_normalized, '\s+', '_', 'g');
    
    -- Step 3: Remove non-alphanumeric characters (keep only a-z, 0-9, _)
    v_normalized := REGEXP_REPLACE(v_normalized, '[^a-z0-9_]', '', 'g');
    
    -- Step 4: Collapse multiple underscores to single underscore
    v_normalized := REGEXP_REPLACE(v_normalized, '_+', '_', 'g');
    
    -- Step 5: Trim leading/trailing underscores
    v_normalized := TRIM(BOTH '_' FROM v_normalized);
    
    RETURN v_normalized;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION normalize_variant_key IS 
    'Normalize variant_key: lowercase, alphanumeric+underscore only, collapse underscores.';


-- -----------------------------------------------------------------------------
-- FIX 3: Update add_product_alias() with strong normalization
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION add_product_alias(
    p_product_id INTEGER,
    p_alias_key TEXT
) RETURNS VOID AS $$
DECLARE
    v_normalized_key TEXT;
BEGIN
    -- Apply strong normalization
    v_normalized_key := normalize_variant_key(p_alias_key);
    
    -- Skip if normalization resulted in empty string
    IF v_normalized_key = '' THEN
        RAISE NOTICE 'Skipping empty alias after normalization: %', p_alias_key;
        RETURN;
    END IF;
    
    INSERT INTO product_aliases (product_id, alias_key)
    VALUES (p_product_id, v_normalized_key)
    ON CONFLICT (alias_key) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION add_product_alias IS 
    'Add normalized alias for a product. Uses strong normalization (alphanumeric+underscore only).';


-- -----------------------------------------------------------------------------
-- FIX 4: Update resolve_product() with strong normalization
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION resolve_product(p_variant_key TEXT) RETURNS INTEGER AS $$
DECLARE
    v_product_id INTEGER;
    v_normalized_key TEXT;
BEGIN
    -- Apply strong normalization
    v_normalized_key := normalize_variant_key(p_variant_key);
    
    -- Return NULL if normalization resulted in empty string
    IF v_normalized_key = '' THEN
        RETURN NULL;
    END IF;
    
    -- Try canonical variant_key
    SELECT id INTO v_product_id FROM products WHERE variant_key = v_normalized_key;
    
    -- Try alias
    IF v_product_id IS NULL THEN
        SELECT product_id INTO v_product_id FROM product_aliases WHERE alias_key = v_normalized_key;
    END IF;
    
    RETURN v_product_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION resolve_product IS 
    'Resolve variant_key to product_id with strong normalization. Checks variant_key and aliases.';


-- -----------------------------------------------------------------------------
-- FIX 5: Update get_or_create_product() with strong normalization
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_or_create_product(
    p_base_product_key TEXT,
    p_variant_key TEXT,
    p_display_name TEXT,
    p_brand TEXT DEFAULT NULL,
    p_category TEXT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_product_id INTEGER;
    v_normalized_base TEXT;
    v_normalized_variant TEXT;
BEGIN
    -- Apply strong normalization
    v_normalized_base := normalize_variant_key(p_base_product_key);
    v_normalized_variant := normalize_variant_key(p_variant_key);
    
    -- Validate normalized keys are not empty
    IF v_normalized_base = '' OR v_normalized_variant = '' THEN
        RAISE EXCEPTION 'Invalid product keys after normalization: base=%, variant=%', 
            p_base_product_key, p_variant_key;
    END IF;
    
    -- Try to find by canonical variant_key
    SELECT id INTO v_product_id FROM products WHERE variant_key = v_normalized_variant;
    
    -- Try to find by alias
    IF v_product_id IS NULL THEN
        SELECT product_id INTO v_product_id FROM product_aliases WHERE alias_key = v_normalized_variant;
    END IF;
    
    -- Create if not exists
    IF v_product_id IS NULL THEN
        INSERT INTO products (base_product_key, variant_key, display_name, brand, category)
        VALUES (v_normalized_base, v_normalized_variant, p_display_name, p_brand, p_category)
        RETURNING id INTO v_product_id;
    END IF;
    
    RETURN v_product_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_or_create_product IS 
    'Get or create product with strong normalization. Checks variant_key and aliases.';


-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Verify user_actions constraints:
-- SELECT conname, contype FROM pg_constraint WHERE conrelid = 'user_actions'::regclass;
-- Expected: uq_user_actions_listing (type 'u')

-- Verify listing_id is NOT NULL:
-- SELECT attname, attnotnull FROM pg_attribute 
-- WHERE attrelid = 'user_actions'::regclass AND attname = 'listing_id';
-- Expected: attnotnull = true

-- Test strong normalization:
-- SELECT normalize_variant_key('Apple iPhone 12 Mini (128GB)');
-- Expected: 'apple_iphone_12_mini_128gb'

-- SELECT normalize_variant_key('Garmin Fenix 7X - Sapphire Solar');
-- Expected: 'garmin_fenix_7x_sapphire_solar'

-- SELECT normalize_variant_key('AirPods Pro (2. Generation)');
-- Expected: 'airpods_pro_2_generation'

-- Test duplicate prevention:
-- SELECT add_product_alias(1, 'Apple iPhone 12 Mini 128GB');
-- SELECT add_product_alias(1, 'apple_iphone_12_mini_128gb');
-- SELECT add_product_alias(1, 'Apple-iPhone-12-Mini-(128GB)');
-- SELECT COUNT(*) FROM product_aliases WHERE product_id = 1;
-- Expected: 1 (all normalize to same key)

-- Test resolve_product:
-- SELECT resolve_product('Apple iPhone 12 Mini 128GB');
-- SELECT resolve_product('apple_iphone_12_mini_128gb');
-- SELECT resolve_product('Apple-iPhone-12-Mini-(128GB)');
-- Expected: All return same product_id

-- Test UPSERT:
-- SELECT set_user_action(123, 'watch', 'Test note');
-- SELECT set_user_action(123, 'purchased', 'Updated note');
-- SELECT COUNT(*) FROM user_actions WHERE listing_id = 123;
-- Expected: 1 (updated, not inserted)

-- Test NOT NULL enforcement (should fail):
-- INSERT INTO user_actions (listing_id, action) VALUES (NULL, 'watch');
-- Expected: ERROR: null value in column "listing_id" violates not-null constraint
