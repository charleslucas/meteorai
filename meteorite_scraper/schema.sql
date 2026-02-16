-- Connect to the meteorite_images database first
-- \c meteorite_images

CREATE TABLE IF NOT EXISTS meteorites (
    image_id SERIAL PRIMARY KEY,
    meteorite_name VARCHAR(255),
    original_filename VARCHAR(500),
    stored_filename VARCHAR(500) UNIQUE NOT NULL,
    source_url TEXT,
    page_url TEXT,
    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Image properties
    file_format VARCHAR(10),
    file_size_bytes INTEGER,
    width_px INTEGER,
    height_px INTEGER,
    image_quality_score DECIMAL(3,2),
    
    -- Classification
    primary_type VARCHAR(50),
    secondary_type VARCHAR(100),
    detailed_classification VARCHAR(100),
    weathering_grade VARCHAR(10),
    
    -- Physical characteristics
    mass_grams DECIMAL(10,2),
    fusion_crust_present BOOLEAN,
    regmaglypts_present BOOLEAN,
    visible_metal BOOLEAN,
    
    -- Discovery info
    fall_or_find VARCHAR(10),
    discovery_date DATE,
    discovery_location TEXT,
    discovery_latitude DECIMAL(9,6),
    discovery_longitude DECIMAL(9,6),
    terrain_type VARCHAR(100),
    
    -- Context (crucial for ML)
    image_context VARCHAR(50),
    viewing_angle VARCHAR(50),
    background_type VARCHAR(100),
    lighting_type VARCHAR(50),
    
    -- Metadata
    license VARCHAR(100),
    photographer VARCHAR(255),
    data_confidence VARCHAR(20),
    needs_review BOOLEAN DEFAULT FALSE,
    notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common queries
CREATE INDEX idx_primary_type ON meteorites(primary_type);
CREATE INDEX idx_image_context ON meteorites(image_context);
CREATE INDEX idx_needs_review ON meteorites(needs_review);
CREATE INDEX idx_source_url ON meteorites(source_url);
CREATE INDEX idx_meteorite_name ON meteorites(meteorite_name);

-- Create a function to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to use the function
CREATE TRIGGER update_meteorites_updated_at 
    BEFORE UPDATE ON meteorites 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Create a table for scraping logs
CREATE TABLE IF NOT EXISTS scrape_logs (
    log_id SERIAL PRIMARY KEY,
    source_name VARCHAR(255),
    scrape_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    images_found INTEGER,
    images_downloaded INTEGER,
    errors INTEGER,
    status VARCHAR(50),
    notes TEXT
);