-- Migration: Add identity_key to listings table
-- Purpose: Persist canonical identity for cross-run aggregation (Phase 4.2/4.3)
-- Date: 2026-02-08
-- Context: Market price aggregation and soft market evaluation require stable
--          canonical identity that excludes storage, color, and condition.

-- Add identity_key column to listings
ALTER TABLE listings ADD COLUMN IF NOT EXISTS identity_key TEXT;

-- Create index for efficient aggregation queries
CREATE INDEX IF NOT EXISTS idx_listings_identity_key ON listings(identity_key);

-- Add comment
COMMENT ON COLUMN listings.identity_key IS 'Canonical product identity excluding storage/color/condition (e.g., apple_iphone_12_mini). Used for cross-variant market price aggregation and soft market evaluation.';

-- Performance note: This index enables fast GROUP BY identity_key queries
-- for market price calculation across multiple runs.
