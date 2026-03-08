-- Migration: Add photo_type column to meteorites table
-- Categorizes the type of photo: Fall, Staged, or Sectioned

-- Add the column (allow NULL for existing records)
ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS photo_type VARCHAR(20);

-- Add comment
COMMENT ON COLUMN meteorites.photo_type IS 'Type of photo: Fall, Staged, or Sectioned';
