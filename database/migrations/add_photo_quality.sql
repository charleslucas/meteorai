-- Migration: Add photo_quality column to meteorites table
-- Rates the quality of the photo: High, Medium, or Low

-- Add the column (allow NULL for existing records)
ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS photo_quality VARCHAR(20);

-- Add comment
COMMENT ON COLUMN meteorites.photo_quality IS 'Quality of photo: High, Medium, or Low';
