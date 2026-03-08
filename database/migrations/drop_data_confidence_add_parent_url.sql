-- Migration: Remove data_confidence column and add parent_url column

-- Drop data_confidence
ALTER TABLE meteorites DROP COLUMN IF EXISTS data_confidence;

-- Add parent_url
ALTER TABLE meteorites ADD COLUMN IF NOT EXISTS parent_url TEXT;

COMMENT ON COLUMN meteorites.parent_url IS 'Parent URL where the meteorite image was found';
