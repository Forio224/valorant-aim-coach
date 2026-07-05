from typing import List, Any
from src.pipeline.base import (
    PipelineContext, PipelineLayer, SensingLayer, EventLayer,
    MetricLayer, PatternLayer, PrioritizationLayer, PresentationLayer,
    SensingResult, EventResult, MetricResult, PatternResult, la_PrioritizedInsight
)

class PipelineManager:
    def __init__(
        self,
        sensing: SensingLayer,
        event: EventLayer,
        metric: MetricLayer,
        pattern: PatternLayer,
        priority: PrioritizationLayer,
        presentation: PresentationLayer
    ):
        self.sensing = sensing
        self.event = event
        self.metric = metric
        self.pattern = pattern
        self.priority = priority
        self.presentation = presentation

    def run(self, context: PipelineContext) -> str:
        # Pipeline flow: Sensing -> Events -> Metrics -> Patterns -> Prioritization -> LLM
        sensing_data = self.sensing.process(context.raw_video_path, context)
        event_data = self.event.process(sensing_data, context)
        metric_data = self.metric.process(event_data, context)
        pattern_data = self.pattern.process(metric_data, context)
        prioritized_insights = self.priority.process(pattern_data, context)

        return self.presentation.process(prioritized_insights, context)

# --- Mock Implementations for Infrastructure Skeleton ---

class MockSensingLayer(SensingLayer):
    def process(self, video_path, context):
        print("[Sensing] Processing video...")
        return [SensingResult(frame_id=i, detections=[], event_quality_score="HIGH", frame_state="NORMAL") for i in range(100)]

class MockEventLayer(EventLayer):
    def process(self, sensing_results, context):
        print("[Event] Extracting combat windows...")
        return [EventResult(engagement_id="eng_1", engagement_type="REACTIVE", start_ms=1000, end_ms=2000, events=[])]

class MockMetricLayer(MetricLayer):
    def process(self, event_results, context):
        print("[Metric] Calculating HU values...")
        return [MetricResult(engagement_id="eng_1", metrics={"placement_offset_y_hu": -0.6}, verdicts={"placement": "LOW"})]

class MockPatternLayer(PatternLayer):
    def process(self, metric_results, context):
        print("[Pattern] Detecting habits...")
        return PatternResult(match_id="match_1", detected_patterns=[{"pattern_id": "low_crosshair_placement", "severity": 0.6, "frequency": 0.8}])

class MockPriorityLayer(PrioritizationLayer):
    def process(self, pattern_result, context):
        print("[Priority] Ranking bottlenecks...")
        return [la_PrioritizedInsight(pattern_id="low_crosshair_placement", fact="Consistent low aim", recommendation="Train head level", evidence_timestamps=[1200], priority=1.0)]

class MockPresentationLayer(PresentationLayer):
    def process(self, insights, context):
        print("[LLM] Generating report...")
        return f"Coach Report: I found {len(insights)} issues. Fix your aim!"

if __name__ == "__main__":
    # Setup context
    ctx = PipelineContext(
        game_profile="valorant",
        user_config={"enemy_highlight_color": "red"},
        raw_video_path="test_video.mp4"
    )

    # Assemble pipeline
    manager = PipelineManager(
        sensing=MockSensingLayer(),
        event=MockEventLayer(),
        metric=MockMetricLayer(),
        pattern=MockPatternLayer(),
        priority=MockPriorityLayer(),
        presentation=MockPresentationLayer()
    )

    # Run skeleton
    report = manager.run(ctx)
    print("\nFinal Output:\n", report)
