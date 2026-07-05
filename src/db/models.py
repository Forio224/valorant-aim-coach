from enum import Enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, ARRAY, JSON, SmallInteger, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()

class GameProfileType(Enum):
    VALORANT = 'valorant'
    CS2 = 'cs2'
    APEX = 'apex'

class EngagementType(Enum):
    REACTIVE = 'REACTIVE'
    HELD = 'HELD'
    PREFIRE = 'PREFIRE'

class QualityScoreType(Enum):
    HIGH = 'HIGH'
    MEDIUM = 'MEDIUM'
    LOW = 'LOW'

class PatternLevelType(Enum):
    FOUNDATIONAL = 'FOUNDATIONAL'
    EXECUTION = 'EXECUTION'
    COGNITIVE = 'COGNITIVE'

class VerdictType(Enum):
    LOW = 'LOW'
    NORMAL = 'NORMAL'
    HIGH = 'HIGH'

class ReportToneType(Enum):
    STRICT_COACH = 'strict_coach'
    SUPPORTIVE_MENTOR = 'supportive_mentor'
    NEUTRAL = 'neutral'

class User(Base):
    __tablename__ = 'users'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    username = Column(String(64), unique=True, nullable=False)
    game_profile = Column(String(32), default='valorant') # Simplified from Enum for DB compatibility

    # Valorant-specific sensing config
    enemy_highlight_color_h_min = Column(SmallInteger)
    enemy_highlight_color_h_max = Column(SmallInteger)
    enemy_highlight_color_s_min = Column(SmallInteger)

    # LLM presentation preferences
    report_tone = Column(String(32), default='strict_coach')
    locale = Column(String(8), default='en')

    sessions = relationship("Session", back_populates="user")

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    game_profile = Column(String(32), nullable=False)

    user = relationship("User", back_populates="sessions")
    matches = relationship("Match", back_populates="session")

class Match(Base):
    __tablename__ = 'matches'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    recorded_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    video_path = Column(Text, nullable=False)
    duration_ms = Column(Integer)
    fps = Column(Float)
    resolution_w = Column(SmallInteger)
    resolution_h = Column(SmallInteger)

    map_name = Column(String(64))
    game_mode = Column(String(32))

    processed_at = Column(DateTime(timezone=True))
    processing_error = Column(Text)

    session = relationship("Session", back_populates="matches")
    engagements = relationship("Engagement", back_populates="match")

class Engagement(Base):
    __tablename__ = 'engagements'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)

    visual_contact_ms = Column(Integer, nullable=False)
    combat_end_ms = Column(Integer, nullable=False)

    engagement_type = Column(String(32), nullable=False)
    event_quality_score = Column(String(32), nullable=False)

    frame_gate_passed = Column(Boolean, default=True, nullable=False)
    yolo_confidence_avg = Column(Float)
    detection_ratio = Column(Float)

    evidence_timestamps_ms = Column(ARRAY(Integer))

    match = relationship("Match", back_populates="engagements")
    metric_set = relationship("MetricSet", back_populates="engagement", uselist=False)

class MetricSet(Base):
    __tablename__ = 'metric_sets'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engagement_id = Column(UUID(as_uuid=True), ForeignKey('engagements.id', ondelete='CASCADE'), unique=True, nullable=False)

    visual_reaction_ms = Column(Integer)
    aim_acquisition_ms = Column(Integer)
    decision_delay_ms = Column(Integer)

    placement_offset_x_hu = Column(Float)
    placement_offset_y_hu = Column(Float)
    placement_verdict = Column(String(32))

    overshoot_distance_hu = Column(Float)
    correction_count = Column(SmallInteger)

    head_level_ratio = Column(Float)

    engagement = relationship("Engagement", back_populates="metric_set")

class PatternInstance(Base):
    __tablename__ = 'pattern_instances'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    pattern_id = Column(String(64), nullable=False)
    kb_schema_version = Column(String(16), nullable=False)

    pattern_level = Column(String(32), nullable=False)
    base_weight = Column(Float, nullable=False)
    frequency = Column(Float, nullable=False)
    severity = Column(Float, nullable=False)
    priority_score = Column(Float, nullable=False)
    severity_override = Column(Boolean, default=False, nullable=False)

    event_quality_score = Column(String(32), nullable=False)

    evidence_engagement_ids = Column(ARRAY(UUID(as_uuid=True)))
    evidence_timestamps_ms = Column(ARRAY(Integer))

class Report(Base):
    __tablename__ = 'reports'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    top_pattern_ids = Column(ARRAY(String(64)))
    llm_prompt_version = Column(String(16), nullable=False)
    llm_input_json = Column(JSON, nullable=False)

    report_text = Column(Text, nullable=False)
    report_tone_used = Column(String(32), nullable=False)

    progress_trend_json = Column(JSON)

class ProgressTrend(Base):
    __tablename__ = 'progress_trends'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    pattern_id = Column(String(64), nullable=False)
    computed_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    window_matches = Column(SmallInteger, nullable=False)
    avg_severity = Column(Float, nullable=False)
    avg_frequency = Column(Float, nullable=False)
    trend_direction = Column(String(16))
    trend_delta_pct = Column(Float)
