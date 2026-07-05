-- ============================================================
-- AI Aim Coach — Telemetry Database Schema
-- Version: 1.0
-- Task: I2.1 — Telemetry Schema
-- Unit of truth: Head Units (HU) for all spatial measurements
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- ENUM Types
-- ============================================================

CREATE TYPE game_profile_type AS ENUM ('valorant', 'cs2', 'apex');
CREATE TYPE engagement_type AS ENUM ('REACTIVE', 'HELD', 'PREFIRE');
CREATE TYPE quality_score_type AS ENUM ('HIGH', 'MEDIUM', 'LOW');
CREATE TYPE pattern_level_type AS ENUM ('FOUNDATIONAL', 'EXECUTION', 'COGNITIVE');
CREATE TYPE verdict_type AS ENUM ('LOW', 'NORMAL', 'HIGH');
CREATE TYPE report_tone_type AS ENUM ('strict_coach', 'supportive_mentor', 'neutral');

-- ============================================================
-- USERS
-- ============================================================

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    username        VARCHAR(64) NOT NULL UNIQUE,
    game_profile    game_profile_type NOT NULL DEFAULT 'valorant',

    -- Valorant-specific sensing config
    enemy_highlight_color_h_min  SMALLINT,   -- HSV Hue min
    enemy_highlight_color_h_max  SMALLINT,   -- HSV Hue max
    enemy_highlight_color_s_min  SMALLINT,   -- HSV Saturation min

    -- LLM presentation preferences
    report_tone     report_tone_type NOT NULL DEFAULT 'strict_coach',
    locale          VARCHAR(8)  NOT NULL DEFAULT 'en'
);

-- ============================================================
-- SESSIONS
-- A session groups one or more matches analysed together
-- (e.g., a single ranked session in one evening)
-- ============================================================

CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    game_profile    game_profile_type NOT NULL
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);

-- ============================================================
-- MATCHES
-- One uploaded video = one match
-- ============================================================

CREATE TABLE matches (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    recorded_at     TIMESTAMPTZ,          -- nullable: extracted from metadata if available
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Video metadata
    video_path      TEXT NOT NULL,        -- path to original MP4/MOV
    duration_ms     INTEGER,              -- total video duration
    fps             REAL,
    resolution_w    SMALLINT,
    resolution_h    SMALLINT,

    -- Game context (if detectable / user-provided)
    map_name        VARCHAR(64),
    game_mode       VARCHAR(32),          -- e.g. 'competitive', 'unrated'

    -- Processing status
    processed_at    TIMESTAMPTZ,
    processing_error TEXT                 -- NULL if no error
);

CREATE INDEX idx_matches_session_id ON matches(session_id);

-- ============================================================
-- ENGAGEMENTS
-- One detected combat window (VisualContact → CombatEngagement)
-- ============================================================

CREATE TABLE engagements (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    match_id        UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,

    -- Temporal bounds (milliseconds from video start)
    visual_contact_ms       INTEGER NOT NULL,
    combat_end_ms           INTEGER NOT NULL,

    -- Classification
    engagement_type         engagement_type NOT NULL,
    event_quality_score     quality_score_type NOT NULL,

    -- Raw quality sub-scores (stored for debugging / calibration)
    frame_gate_passed       BOOLEAN NOT NULL DEFAULT TRUE,
    yolo_confidence_avg     REAL,        -- average L2 confidence in window
    detection_ratio         REAL,        -- L3: frames_with_detection / total_frames

    -- Evidence: reference frame timestamps for LLM report links
    evidence_timestamps_ms  INTEGER[]    -- array of key frame timestamps
);

CREATE INDEX idx_engagements_match_id ON engagements(match_id);
CREATE INDEX idx_engagements_type ON engagements(engagement_type);

-- ============================================================
-- METRIC SETS
-- Calculated metrics for one engagement
-- All spatial values in Head Units (HU)
-- ============================================================

CREATE TABLE metric_sets (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id           UUID NOT NULL UNIQUE REFERENCES engagements(id) ON DELETE CASCADE,

    -- Timing metrics (milliseconds, NULL if not applicable for engagement_type)
    visual_reaction_ms      INTEGER,     -- VisualContact → first input
    aim_acquisition_ms      INTEGER,     -- VisualContact → CrosshairOnTarget
    decision_delay_ms       INTEGER,     -- CrosshairOnTarget → ShotFired

    -- Placement metrics (HU = offset / head_height_px)
    placement_offset_x_hu   REAL,        -- horizontal offset at VisualContact
    placement_offset_y_hu   REAL,        -- vertical offset at VisualContact (negative = below head)
    placement_verdict       verdict_type, -- LOW / NORMAL / HIGH (classified from offset_y)

    -- Flick metrics (NULL for HELD / PREFIRE)
    overshoot_distance_hu   REAL,        -- distance past target boundary
    correction_count        SMALLINT,    -- number of corrections after overshoot

    -- Tracking quality
    head_level_ratio        REAL         -- % of engagement time crosshair was within 0.5 HU of head center
);

-- ============================================================
-- PATTERN INSTANCES
-- Detected systematic patterns per match
-- References the Knowledge Base pattern_id (external JSON)
-- ============================================================

CREATE TABLE pattern_instances (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    match_id            UUID NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Reference to KB JSON entry
    pattern_id          VARCHAR(64) NOT NULL,   -- e.g. 'low_crosshair_placement'
    kb_schema_version   VARCHAR(16) NOT NULL,   -- KB version at time of detection

    -- Pattern scoring
    pattern_level       pattern_level_type NOT NULL,
    base_weight         REAL NOT NULL,
    frequency           REAL NOT NULL,  -- ratio of qualifying engagements
    severity            REAL NOT NULL,  -- avg deviation from threshold
    priority_score      REAL NOT NULL,  -- base_weight × frequency × severity
    severity_override   BOOLEAN NOT NULL DEFAULT FALSE,

    -- Data quality gate
    event_quality_score quality_score_type NOT NULL,  -- worst score in contributing events

    -- Evidence links
    evidence_engagement_ids UUID[],     -- engagements that triggered this pattern
    evidence_timestamps_ms  INTEGER[]   -- specific frame timestamps for report
);

CREATE INDEX idx_pattern_instances_match_id ON pattern_instances(match_id);
CREATE INDEX idx_pattern_instances_pattern_id ON pattern_instances(pattern_id);

-- ============================================================
-- REPORTS
-- LLM-generated coaching reports
-- ============================================================

CREATE TABLE reports (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id          UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Top patterns selected for this report (ordered by priority)
    top_pattern_ids     VARCHAR(64)[],  -- max 3 entries

    -- LLM inputs (stored for debugging / re-generation)
    llm_prompt_version  VARCHAR(16) NOT NULL,
    llm_input_json      JSONB NOT NULL,   -- full structured input sent to LLM

    -- LLM output
    report_text         TEXT NOT NULL,   -- final coaching report
    report_tone_used    report_tone_type NOT NULL,

    -- Progress context used
    progress_trend_json JSONB            -- snapshot of trend at generation time
);

CREATE INDEX idx_reports_user_id ON reports(user_id);
CREATE INDEX idx_reports_session_id ON reports(session_id);

-- ============================================================
-- PROGRESS TRENDS
-- Aggregated per-user per-pattern metric history
-- Enables "Overall Progress Trend" in LLM input
-- ============================================================

CREATE TABLE progress_trends (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pattern_id          VARCHAR(64) NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Rolling averages (last N matches, configurable)
    window_matches      SMALLINT NOT NULL,   -- how many matches in this window
    avg_severity        REAL NOT NULL,
    avg_frequency       REAL NOT NULL,
    trend_direction     VARCHAR(16),         -- 'improving', 'stable', 'degrading'
    trend_delta_pct     REAL                 -- % change vs previous window
);

CREATE INDEX idx_progress_trends_user_pattern ON progress_trends(user_id, pattern_id);


-- ============================================================
-- USEFUL VIEWS
-- ============================================================

-- Per-match summary: top pattern + aggregate placement verdict
CREATE VIEW match_summary AS
SELECT
    m.id                    AS match_id,
    m.session_id,
    m.recorded_at,
    m.map_name,
    COUNT(e.id)             AS total_engagements,
    AVG(ms.placement_offset_y_hu) AS avg_placement_offset_y_hu,
    MODE() WITHIN GROUP (ORDER BY ms.placement_verdict) AS dominant_placement_verdict,
    AVG(ms.visual_reaction_ms)    AS avg_visual_reaction_ms,
    AVG(ms.aim_acquisition_ms)    AS avg_aim_acquisition_ms
FROM matches m
JOIN engagements e  ON e.match_id = m.id
JOIN metric_sets ms ON ms.engagement_id = e.id
WHERE e.event_quality_score IN ('HIGH', 'MEDIUM')
GROUP BY m.id;

-- Per-user placement trend (last 10 matches)
CREATE VIEW user_placement_trend AS
SELECT
    s.user_id,
    m.id AS match_id,
    m.recorded_at,
    AVG(ms.placement_offset_y_hu) AS avg_offset_y_hu,
    COUNT(e.id) FILTER (WHERE ms.placement_verdict = 'LOW')  AS low_count,
    COUNT(e.id) FILTER (WHERE ms.placement_verdict = 'NORMAL') AS normal_count,
    COUNT(e.id) FILTER (WHERE ms.placement_verdict = 'HIGH') AS high_count
FROM sessions s
JOIN matches m     ON m.session_id = s.id
JOIN engagements e ON e.match_id = m.id
JOIN metric_sets ms ON ms.engagement_id = e.id
WHERE e.event_quality_score IN ('HIGH', 'MEDIUM')
GROUP BY s.user_id, m.id, m.recorded_at
ORDER BY s.user_id, m.recorded_at DESC;