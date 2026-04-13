-- Migration: add file_hash column to meteorites table
-- Run once against the meteorite_images database, then run backfill_hashes.py

ALTER TABLE meteorites ADD COLUMN IF NOT EXISTS file_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS meteorites_file_hash_idx
    ON meteorites (file_hash)
    WHERE file_hash IS NOT NULL;
