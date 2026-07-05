# Design Specification: AI Aim Coach Architecture

**Date:** 2026-06-01
**Status:** Draft for Review
**Topic:** Scalable Architecture for Personalized AI Aim Training

## 1. Product Vision
The AI Aim Coach is an expert system designed for ambitious gamers striving for professional or high-rank performance (e.g., Immortal/Radiant in Valorant). Unlike simple aim trackers, this service focuses on **interpreting** gameplay data to identify cognitive and mechanical bottlenecks.

### Core Value Proposition
Moving from "What happened" (statistics) to "Why it happened" (insights) and "How to fix it" (actionable training plans).

### Monetization Strategy
SaaS Subscription model. Value increases as the system tracks progress over time and iteratively optimizes the user's training plan based on new match data.

---

## 2. System Architecture (The Truth-to-Interpretation Pipeline)

The architecture is designed as a unidirectional pipeline to ensure determinism, eliminate LLM hallucinations in analysis, and allow for scalable updates.

### 2.1 Pipeline Flow
`Sensing` $\rightarrow$ `Events` $\rightarrow$ `Metrics` $\rightarrow$ `Patterns` $\rightarrow$ `Prioritization` $\rightarrow$ `Confidence` $\rightarrow$ `Knowledge Base` $\rightarrow$ `Advice Builder` $\rightarrow$ `LLM (Presentation)`

### 2.2 Layer Definitions

#### A. Sensing Layer (CV)
Extracts raw visual data from video frames.
- **Outputs:** Cursor coordinates $(x, y)$, enemy bounding boxes, shot flashes, killfeed events.

#### B. Event Layer (The Facts)
Converts raw data into discrete, objective game events.
- **Key Events:**
    - `EnemyAppeared`: Enemy first enters frame or line-of-sight.
    - `CrosshairPlacementSnapshot`: Captures cursor pos relative to head level immediately before contact.
    - `FlickStarted`: Sharp acceleration towards a target.
    - `TargetPassed`: Cursor crosses target boundary without stopping.
    - `CrosshairOnTarget`: Cursor enters the target's hit-box radius.
    - `FlickEnded`: Deceleration or shot fired.
    - `ShotFired`: Detection of weapon discharge.
    - `FirstHit`: First registered damage to enemy.
    - `KillConfirmed`: Enemy death event.
    - `EngagementStarted`: Triggered by visibility or first shot.
    - `EngagementEnded`: Triggered by death, kill, or loss of contact.

#### C. Metrics Layer (The Numbers)
Calculates mathematical values from event windows (Engagement start $\rightarrow$ end).
- **Reaction:** `VisualReaction` (Appeared $\rightarrow$ Shot), `AimAcquisition` (Appeared $\rightarrow$ OnTarget), `DecisionDelay` (OnTarget $\rightarrow$ Shot).
- **Flicking:** `InitialError` (distance at start), `OvershootDistance` (past TargetPassed), `CorrectionCount`.
- **Placement:** `VerticalOffset` (Head-level distance), `Head-Level Ratio` (% of time on head-level).

#### D. Pattern Detection Layer (The Habits)
Identifies systematic behaviors rather than one-off errors.
- **Logic:** Uses confidence scores based on frequency, stability across matches, and degree of deviation.
- **MVP Patterns:**
    - `systematic_overshoot`: High frequency of `TargetPassed` events.
    - `low_crosshair_placement`: Consistent negative `VerticalOffset`.
    - `slow_aim_acquisition`: Consistently high `AimAcquisitionTime` despite fast `VisualReaction`.

#### E. Prioritization Layer (Strategy)
Ranks patterns by their impact on the game outcome (e.g., a 10px placement error is more critical than a 10ms reaction delay).
- **Goal:** Select the top 2-3 "bottlenecks" to avoid overwhelming the user.

#### F. Confidence Layer (Validation)
Filters results based on data quality.
- **Criteria:** `EventQualityScore` (CV precision), `ContextValidity` (Exclude flash-bangs, smokes, or extreme distances).
- **Gate:** Only patterns with high confidence proceed to the Knowledge Base.

#### G. Coaching Knowledge Base (Expertise)
A deterministic mapping of `PatternID` to expertise.
- **Contents:** Problem explanation, criticality level, causes, specific drills (e.g., AimLabs scenario names), and correction logic.

#### H. Deterministic Advice Builder (Logic)
Combines the prioritized pattern with the Knowledge Base to create a "Fact + Action" pair.
- **Output:** `Insight` (The Fact) + `Recommendation` (The Action).

#### I. LLM Presentation Layer (Communication)
Transforms structured data into a human-centric, motivating coaching report.
- **Role:** ONLY presentation, personalization, and synthesis.
- **Inputs:** User profile, Prioritized Insights, Recommendations, Training Drills.
- **Output:** Personalized Coach Report and Weekly Training Plan.

---

## 3. MVP Scope

### 3.1 Target Metrics
1. **Crosshair Placement**: Vertical/Horizontal offset, Head-level ratio.
2. **Flick Accuracy**: Overshoot distance, correction counts.
3. **Reaction Time**: Visual reaction vs. Aim acquisition vs. Decision delay.

### 3.2 Deliverables
- Video processing pipeline capable of generating the `Event Stream`.
- Metric calculators for the 3 target areas.
- A set of 5-10 hard-coded rules for pattern detection.
- LLM integration for generating the final report.

---

## 4. Future Roadmap (V2+)
- **Data-Driven Benchmarks**: Integrate Immortal/Radiant replay data to provide "Comparison to Pro" metrics.
- **Dynamic Drill Adjustment**: Adjust drill difficulty/type based on the improvement of specific metrics.
- **Real-time Overlay**: Move from replay analysis to real-time feedback (if game rules allow).
- **Complex Tactical Analysis**: Positioning, utility usage, and decision-making patterns.
