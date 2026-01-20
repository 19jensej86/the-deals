-- =============================================================================
-- Schema v2.2.1 PATCH - Correctness Fixes
-- =============================================================================
-- Apply this patch AFTER creating schema_v2.2_FINAL.sql
-- 
-- Issues Fixed:
--   1. user_actions: Missing UNIQUE constraint for UPSERT (ON CONFLICT requires it)
--   2. product_aliases: No normalization in add_product_alias() (GB vs gb duplicates)
--   3. Views: Already correct (use started_at DESC, not MAX(run_id))
-- =============================================================================

-- -----------------------------------------------------------------------------
-- FIX 1: user_actions UNIQUE constraint for UPSERT
-- -----------------------------------------------------------------------------
-- Problem: set_user_action() uses ON CONFLICT (listing_id), but there's no UNIQUE constraint.
-- The table has PRIMARY KEY(id), which doesn't prevent duplicate listing_id rows.
-- Solution: Add UNIQUE constraint on listing_id (for listing-scoped actions).

ALTER TABLE user_actions 
    ADD CONSTRAINT uq_user_actions_listing UNIQUE (listing_id);

COMMENT ON CONSTRAINT uq_user_actions_listing ON user_actions IS 
    'Ensures one action per listing. Required for set_user_action() UPSERT.';


-- -----------------------------------------------------------------------------
-- FIX 2: product_aliases normalization
-- -----------------------------------------------------------------------------
-- Problem: add_product_alias() doesn't normalize alias_key, allowing duplicates like:
--   - 'apple_iphone_12_mini_128GB' (uppercase GB)
--   - 'apple_iphone_12_mini_128gb' (lowercase gb)
-- Solution: Normalize alias_key to lowercase with underscores before insert.

CREATE OR REPLACE FUNCTION add_product_alias(
    p_product_id INTEGER,
    p_alias_key TEXT
) RETURNS VOID AS $$
DECLARE
    v_normalized_key TEXT;
BEGIN
    -- Normalize: lowercase, trim whitespace, replace spaces with underscores
    v_normalized_key := LOWER(TRIM(REGEXP_REPLACE(p_alias_key, '\s+', '_', 'g')));
    
    INSERT INTO product_aliases (product_id, alias_key)
    VALUES (p_product_id, v_normalized_key)
    ON CONFLICT (alias_key) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION add_product_alias IS 
    'Add normalized alias for a product. Normalizes to lowercase with underscores.';


-- -----------------------------------------------------------------------------
-- FIX 3: resolve_product() normalization (consistency)
-- -----------------------------------------------------------------------------
-- Problem: resolve_product() should also normalize input for consistent lookups.
-- Solution: Apply same normalization before lookup.

CREATE OR REPLACE FUNCTION resolve_product(p_variant_key TEXT) RETURNS INTEGER AS $$
DECLARE
    v_product_id INTEGER;
    v_normalized_key TEXT;
BEGIN
    -- Normalize input
    v_normalized_key := LOWER(TRIM(REGEXP_REPLACE(p_variant_key, '\s+', '_', 'g')));
    
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
    'Resolve variant_key to product_id with normalization. Checks both variant_key and aliases.';


-- -----------------------------------------------------------------------------
-- FIX 4: get_or_create_product() normalization (consistency)
-- -----------------------------------------------------------------------------
-- Problem: get_or_create_product() should normalize variant_key and base_product_key.
-- Solution: Apply normalization before insert/lookup.

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
    -- Normalize keys
    v_normalized_base := LOWER(TRIM(REGEXP_REPLACE(p_base_product_key, '\s+', '_', 'g')));
    v_normalized_variant := LOWER(TRIM(REGEXP_REPLACE(p_variant_key, '\s+', '_', 'g')));
    
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
    'Get or create product with normalized keys. Checks variant_key and aliases.';


-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Verify user_actions UNIQUE constraint exists:
-- SELECT conname, contype FROM pg_constraint WHERE conrelid = 'user_actions'::regclass;
-- Expected: uq_user_actions_listing (type 'u')

-- Test normalization:
-- SELECT add_product_alias(1, 'Apple iPhone 12 Mini 128GB');
-- SELECT add_product_alias(1, 'apple_iphone_12_mini_128gb');
-- SELECT * FROM product_aliases WHERE product_id = 1;
-- Expected: Only one row with normalized key 'apple_iphone_12_mini_128gb'

-- Test resolve_product normalization:
-- SELECT resolve_product('Apple iPhone 12 Mini 128GB');
-- SELECT resolve_product('apple_iphone_12_mini_128gb');
-- Expected: Both return same product_id
