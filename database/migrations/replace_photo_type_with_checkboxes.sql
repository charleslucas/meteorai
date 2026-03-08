-- Migration: Replace photo_type dropdown with in_situ and sectioned boolean columns
-- "Fall" entries become in_situ = TRUE
-- "Sectioned" entries become sectioned = TRUE

-- Add the new boolean columns
ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS in_situ BOOLEAN DEFAULT FALSE;

ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS sectioned BOOLEAN DEFAULT FALSE;

-- Migrate existing data
UPDATE meteorites SET in_situ = TRUE WHERE photo_type = 'Fall';
UPDATE meteorites SET sectioned = TRUE WHERE photo_type = 'Sectioned';

-- Add comments
COMMENT ON COLUMN meteorites.in_situ IS 'Whether the photo shows the meteorite in situ (as found)';
COMMENT ON COLUMN meteorites.sectioned IS 'Whether the photo shows a sectioned/cut meteorite';
