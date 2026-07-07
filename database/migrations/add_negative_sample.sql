-- Migration: Add negative_sample boolean column
-- Marks images used as negative training samples (no meteorite present)

ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS negative_sample BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN meteorites.negative_sample IS 'Whether this image is a negative training sample (no meteorite present)';
