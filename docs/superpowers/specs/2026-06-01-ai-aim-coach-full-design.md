# Full Technical Design: AI Aim Coach

**Date:** 2026-06-01
**Status:** Final Specification (Pending Spike Validation)
**Version:** 1.0
**Topic:** Scalable Architecture for Personalized AI Aim Training

---

## 1. Product Vision & Core Value
The AI Aim Coach transforms raw gameplay footage into actionable cognitive and mechanical training plans. It moves from "What happened" (stats) to "Why it happened" (insights) and "How to fix it" (drills).

### Key Principles
- **Deterministic Analysis:** No LLM guesswork in metrics. Data $\rightarrow$ Patterns $\rightarrow$ Advice.
- **Evidence-Based:** Every insight must be linked to a specific timestamp/event.
- **Scalable Accuracy:** Design for "Expert Weights" today $\rightarrow$ "Pro Benchmarks" tomorrow.
- **Anti-Cheat Safe:** Post-factum analysis of MP4/MOV files.

---

## 2. High-Level Architecture (The Pipeline)

The system is a unidirectional pipeline:
`Input` $\rightarrow$ `Sensing` $\rightarrow$ `Events` $\rightarrow$ `Metrics` $\rightarrow$ `Patterns` $\rightarrow$ `Prioritization` $\rightarrow$ `Knowledge Base` $\rightarrow$ `LLM Presentation`

### 2.1 Game Profiles Layer (Abstracting the Source)
To support multiple games, the pipeline starts with a `GameProfile` configuration.
- **Valorant Profile:** 
    - Source: Computer Vision (CV) pipeline.
    - Config: `enemy_highlight_color` (HSV range).
    - Model: Hybrid HSV $\rightarrow$ YOLOv8/v10.
- **CS2 Profile:**
    - Source: Game State Integration (GSI) / Demo parser.
    - Config: Authoritative coordinate streams.
    - Benefit: Zero-latency, 100% accuracy on positioning.

### 2.2 Sensing Layer (The Eyes)
#### A. Detection Pipeline (Hybrid Approach)
1. **Frame Gate (L1):** 
    - **Flash Detection:** High average brightness $\rightarrow$ Freeze pipeline for $N$ frames.
    - **Smoke Detection:** Low saturation + high grey ratio $\rightarrow$ Mark as `LowVisibility`.
2. **Detection Gate (L2):** 
    - **HSV Masking:** Isolate ROI based on `enemy_highlight_color`.
    - **YOLO Inference:** Run detection only on ROI patches.
    - **Confidence Threshold:** $> 0.65$ (Confirmed), $0.4-0.65$ (Unconfirmed).
3. **Engagement Gate (L3):**
    - **Temporal Stability:** Analyze a 10-frame window.
    - **Detection Ratio:** Ratio of frames with confirmed detections.
    - **Jitter Check:** Bounding box position jumps $> 30\text{px}$ without a velocity vector $\rightarrow$ penalty.

**Output:** `EventQualityScore` (HIGH/MEDIUM/LOW).

#### B. Normalization (The Unit of Truth)
All spatial measurements are normalized to **Head Units (HU)** to ensure independence from resolution, FOV, and distance.
$$\text{Offset}_{HU} = \frac{\text{Offset}_{px}}{\text{HeadHeight}_{px}}$$

---

## 3. Event & Metric Logic

### 3.1 Engagement Classification
The system uses a `PreEngagement Context Flag` to categorize combat windows.

| Type | Trigger Condition | Key Metrics to Calculate |
| :--- | :--- | :--- |
| **REACTIVE** | $\text{Offset} > 30\text{px}$ AND $\text{Velocity}$ NOT towards target | `VisualReaction`, `AimAcquisition`, `DecisionDelay` |
| **HELD** | $\text{Offset} < 15\text{px}$ AND $\text{Velocity} \approx 0$ | `VisualReaction`, `DecisionDelay` |
| **PREFIRE** | $\text{Offset} < 15\text{px}$ AND $\text{Velocity}$ already towards target | `CrosshairPlacement` (Only) |

### 3.2 Metric Definitions
- **Visual Reaction:** Time from `VisualContact` to first input.
- **Aim Acquisition:** Time from `VisualContact` to `CrosshairOnTarget`.
- **Decision Delay:** Time from `CrosshairOnTarget` to `ShotFired`.
- **Placement Offset:** $\Delta x, \Delta y$ (in HU) at moment of `VisualContact`.

---

## 4. Pattern Detection & Prioritization

### 4.1 Pattern Layer
Identifies systematic behaviors using `EventQualityScore`. If the score is below the pattern's `min_quality_score`, the event is ignored for that specific pattern.

### 4.2 Prioritization (Hierarchical Weighted Priority)
Patterns are ranked by:
1. **Strict Hierarchy (Level):** L1 (Foundation) $\rightarrow$ L2 (Execution) $\rightarrow$ L3 (Cognitive).
2. **Weighted Score:** Within a level, $\text{Priority} = \text{BaseWeight} \times \text{Frequency} \times \text{Severity}$.
3. **Severity Override:** If $\text{Severity} > \text{CRITICAL\_THRESHOLD}$, pattern jumps to Top-3 regardless of level.

**V2 Path:** `base_weight` will be replaced by `Bottleneck Delta` (Actual vs. Pro IdealValue).

---

## 5. Knowledge Base & LLM Presentation

### 5.1 KB Structure (JSON)
Each entry contains:
- `id`: Unique identifier.
- `schema_version`: For migration tracking.
- `metric_source`: Linked metric(s) that trigger this insight.
- `min_quality_score`: Minimum confidence required to show this.
- `criticality`: Enum (Foundational, Moderate, Minor).
- `measured_fact`: Template for the objective finding.
- `hypothesized_cause`: Possible reasons (marked as hypotheses).
- `drills`: List of target scenarios (e.g., AimLabs names).
- `correction_logic`: Machine-readable target threshold.
- `evidence_timestamp`: Reference to specific match moments.

### 5.2 LLM Presentation Layer
**Role:** Synthesis, Personalization, and Motivation.
- **Strict Constraint:** LLM is forbidden from fabricating numbers or presenting `hypothesized_cause` as an absolute diagnosis.
- **Prompt Input:** `[User Profile] + [Top 3 Prioritized Insights (Fact + Hypothesis + Drill + Evidence)] + [Progress Trend]`.
- **Output:** Personalized Coach Report.

---

## 6. Telemetry & Data Persistence

### 6.1 Storage Schema
The system tracks longitudinal progress via a relational structure:
`User` $\rightarrow$ `Session` $\rightarrow$ `Match` $\rightarrow$ `MetricSet`.
- **MetricSet:** Stores the raw HU values and flags for every engagement in a match.
- **Progress Trend:** Aggregates `MetricSet` over time to detect improvement in specific patterns.

---

## 7. Appendix: Validation Protocol (Spike Rev. 2)

This design is considered **Provisional** until the following spike is passed:
- **Dataset:** 30 adversarial clips (Control, Target, Noise).
- **Ground Truth:** Hand-labeled $\Delta x, \Delta y$ with Inter-rater reliability check.
- **Success Criteria:**
    1. **Point Accuracy:** $\text{MAE} \le 0.125 \text{ HU}$ (25% of decision boundary).
    2. **Verdict Accuracy:** $> 90\%$ correct classification of `LOW/NORMAL/HIGH` placement.
- **Kill Switch:** If Verdict Accuracy $< 70\%$, the CV stack is pivoted to GSI-first (CS2) or a different model.

---
