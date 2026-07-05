from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional
from dataclasses import dataclass

@dataclass
class PipelineContext:
    """Shared state passed between pipeline layers."""
    game_profile: str
    user_config: Dict[str, Any]
    raw_video_path: str

@dataclass
class SensingResult:
    frame_id: int
    detections: List[Dict[str, Any]]  # Bounding boxes, confidence, etc.
    event_quality_score: str          # HIGH, MEDIUM, LOW
    frame_state: str                  # NORMAL, FLASHED, SMOKED

@dataclass
class EventResult:
    engagement_id: str
    engagement_type: str              # REACTIVE, HELD, PREFIRE
    start_ms: int
    end_ms: int
    events: List[Dict[str, Any]]     # Discrete game events

@dataclass
class MetricResult:
    engagement_id: str
    metrics: Dict[str, float]         # HU and ms values
    verdicts: Dict[str, str]         # LOW/NORMAL/HIGH

@dataclass
class PatternResult:
    match_id: str
    detected_patterns: List[Dict[str, Any]] # pattern_id, score, severity, etc.

@dataclass
 la_PrioritizedInsight:
    pattern_id: str
    fact: str
    recommendation: str
    evidence_timestamps: List[int]
    priority: float

class PipelineLayer(ABC):
    @abstractmethod
    def process(self, input_data: Any, context: PipelineContext) -> Any:
        pass

class SensingLayer(PipelineLayer):
    @abstractmethod
    def process(self, video_path: str, context: PipelineContext) -> List[SensingResult]:
        pass

class EventLayer(PipelineLayer):
    @abstractmethod
    def process(self, sensing_results: List[SensingResult], context: PipelineContext) -> List[EventResult]:
        pass

class MetricLayer(PipelineLayer):
    @abstractmethod
    def process(self, event_results: List[EventResult], context: PipelineContext) -> List[MetricResult]:
        pass

class PatternLayer(PipelineLayer):
    @abstractmethod
    def process(self, metric_results: List[MetricResult], context: PipelineContext) -> PatternResult:
        pass

class PrioritizationLayer(PipelineLayer):
    @abstractmethod
    def process(self, pattern_result: PatternResult, context: PipelineContext) -> List[la_PrioritizedInsight]:
        pass

class PresentationLayer(PipelineLayer):
    @abstractmethod
    def process(self, insights: List[la_PrioritizedInsight], context: PipelineContext) -> str:
        pass
