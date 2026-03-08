-- Migration: Add photo_page_url column to meteorites table
-- This allows us to check if a photo page has already been processed
-- without making HTTP requests to resolve it again

-- Add the column (allow NULL for existing records)
ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS photo_page_url TEXT;

-- Create an index for faster lookups
CREATE INDEX IF NOT EXISTS idx_meteorites_photo_page_url
ON meteorites(photo_page_url);

-- Add comment
COMMENT ON COLUMN meteorites.photo_page_url IS 'URL of the photo detail page (e.g., get_original_photo.cfm?recno=123) before resolution to actual image URL';
