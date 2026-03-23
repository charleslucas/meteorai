-- Migration: Add from_drone boolean column
-- Indicates whether the image or video was captured from a drone.

ALTER TABLE meteorites
ADD COLUMN IF NOT EXISTS from_drone BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN meteorites.from_drone IS 'Whether the image or video was captured from a drone';
