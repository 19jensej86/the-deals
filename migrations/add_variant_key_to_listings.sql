-- Migration: Add variant_key to listings table
-- Purpose: Enable live auction pricing by grouping listings by variant_key
-- Date: 2026-02-01

-- Add variant_key column to listings
ALTER TABLE listings ADD COLUMN IF NOT EXISTS variant_key TEXT;

-- Create index for efficient grouping
CREATE INDEX IF NOT EXISTS idx_listings_variant_key ON listings(variant_key);

-- Add comment
COMMENT ON COLUMN listings.variant_key IS 'Product variant identifier for grouping listings in market pricing (e.g., apple_iphone_12_mini_128gb)';
