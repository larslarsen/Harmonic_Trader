# Deep Research Report: State of the Art in Algorithms for Identifying Fibonacci Retracements and Harmonic Trading Patterns

**Focus**: Detection of Fibonacci-based harmonic patterns (Gartley, Bat, Butterfly, Crab, Shark, Cypher, 5-0, and advanced Scott Carney patterns) with emphasis on information useful for designing machine learning models.

**Date**: 21 July 2026

---

## 1. Background and Core Concepts

Harmonic patterns are geometric price structures defined by precise Fibonacci retracement and extension ratios. They consist of five points (X-A-B-C-D) forming four legs. The key idea, popularized and systematized by **Scott Carney**, is that specific combinations of Fibonacci ratios create high-probability Potential Reversal Zones (PRZ) at point D.

**Classic patterns and key ratios** (approximate ideal values):

| Pattern     | AB of XA     | BC of AB          | CD / XA or other key ratios          | Notes |
|-------------|--------------|-------------------|--------------------------------------|-------|
| Gartley    | 0.618       | 0.382–0.886      | D ≈ 0.786 XA                        | Original H.M. Gartley + Carney refinements |
| Bat        | 0.382–0.50  | 0.382–0.886      | D ≈ 0.886 XA                        | Carney – often considered highly reliable |
| Butterfly  | 0.786       | 0.382–0.886      | D = 1.27–1.618 XA extension         | Gilmore / Carney |
| Crab       | 0.382–0.618 | 0.382–0.886      | D ≈ 1.618 XA                        | Extreme extension |
| Shark      | Specific    | —                | 0.886 / 1.13 structures             | Carney advanced |
| Cypher     | 0.382–0.618 | 1.13–1.414       | Specific                            | More recent |
| 5-0        | —           | —                | Distinct structure                  | Carney |

Scott Carney’s books (*Harmonic Trading* Vol. 1–3) and his official **Harmonic Pattern Collection** software remain the gold standard for definitions and “harmonic zones.”

---

## 2. Traditional Algorithmic Detection Pipeline (State of the Art Rule-Based)

Virtually all production systems follow this pipeline:

1. **Swing / Pivot Point Detection**
   - ZigZag indicator (most common)
   - Fractal indicators
   - Local extrema with prominence / distance filters
   - Directional Change algorithms
   - Multi-scale or adaptive ZigZag (different deviation percentages)

2. **Candidate Structure Generation**
   - Sequential selection of alternating swing highs/lows to form XABCD
   - Filtering by minimum leg length (price or time) and maximum lookback

3. **Fibonacci Ratio Calculation**
   - Retracements: AB/XA, BC/AB, AD/XA, CD/BC, etc.
   - Extensions: CD relative to XA or BC
   - Time ratios sometimes included (less common)

4. **Pattern Matching with Tolerance**
   - Compare calculated ratios against ideal tables
   - Tolerance is critical: typical values are **±0.01 to ±0.05 absolute** or **1–5% relative**
   - Stricter tolerance → higher precision, lower recall
   - Looser tolerance → more signals, lower quality (win rates drop noticeably beyond ~±2–3%)

5. **PRZ Definition and Confirmation**
   - Cluster of Fibonacci projections at D
   - Optional filters: volume, RSI divergence, candlestick confirmation, multi-timeframe alignment

**Commercial & Open Implementations**:
- Scott Carney’s Harmonic Pattern Collection (optimized proprietary algorithms that go beyond simple extremes)
- TradingView scripts (Trendoscope, LuxAlgo, many free/open-source XABCD detectors)
- MetaTrader indicators (Shepherd, Harmonic Pattern Finder, etc.)
- Python libraries: `pyharmonics`, various GitHub ZigZag + ratio checkers (e.g., neurotrader, djoffrey/HarmonicPatterns)

---

## 3. Machine Learning Approaches

Pure end-to-end deep learning for harmonic patterns is still relatively immature compared to rule-based systems, but several directions exist:

**Common Hybrid Approaches** (most practical):
- Use ZigZag / pivots as strong preprocessing
- Feed sequences of normalized ratios, leg lengths (price + time), angles, or relative positions into classifiers (Random Forest, XGBoost, LSTM, Transformer)
- Or treat the five points + ratios as a feature vector for supervised classification

**Computer Vision Approaches**:
- Render chart images (candlesticks + optional overlays)
- Use CNNs or Vision Transformers to detect pattern shapes
- Less precise on exact Fibonacci ratios but better at capturing visual “gestalt”

**Sequence Models**:
- LSTM / GRU / Temporal Convolutional Networks on price or return sequences
- Attention mechanisms to focus on potential pivot locations

**Challenges Specific to ML Design**:
- **Labeling difficulty**: Expert labels are expensive and subjective. Most practical systems use rule-based pseudo-labels with controlled tolerance, then train ML to filter or rank them.
- **Class imbalance**: True high-quality patterns are rare.
- **Scale and noise sensitivity**: Patterns exist across timeframes; noise on lower timeframes destroys ratio precision.
- **Non-stationarity**: Market regimes change ratio effectiveness.
- **Evaluation**: Pattern detection accuracy alone is insufficient — must measure subsequent price reaction in the PRZ (reversal success rate, risk-reward realization).

**Useful Feature Sets for ML**:
- Normalized Fibonacci ratios (primary)
- Relative leg lengths (price distance and bar count)
- Slope / angle of each leg
- Volume profile or volume at pivots
- Volatility regime (ATR relative)
- Multi-timeframe context features
- Distance to round numbers or previous structure
- Confluence score (how tightly Fibonacci levels cluster at D)

---

## 4. Key Design Recommendations for an ML Model

1. **Strong Rule-Based Front-End**  
   Generate high-recall candidate XABCD structures with moderate tolerance using adaptive ZigZag. Let the ML model act as a precision filter / ranker / confidence scorer.

2. **Tolerance Handling**  
   Train with soft labels or multiple tolerance levels. Or predict continuous ratio errors and pattern probability jointly.

3. **Multi-Task Learning**  
   Simultaneously predict: pattern type, completion probability, expected reversal strength, and optimal stop/target placement.

4. **Data Strategy**  
   - Large multi-asset, multi-timeframe historical data
   - Synthetic data augmentation by stretching/compressing valid patterns within tolerance
   - Careful walk-forward or purged cross-validation to avoid leakage

5. **Evaluation Metrics**  
   - Detection: Precision, Recall, F1 at different tolerance levels
   - Trading relevance: Win rate after PRZ touch, average R-multiple, maximum adverse excursion
   - Calibration of confidence scores

6. **Hybrid Deployment**  
   Real-time: Fast ZigZag + ratio engine → ML scoring → alert only high-confidence setups. This matches how professional harmonic software operates.

---

## 5. Current Limitations and Research Gaps

- Very few rigorous academic papers with large-scale statistical validation of automatic harmonic detectors.
- Most “ML harmonic” work is still hybrid and proprietary.
- Official Carney software algorithms remain closed-source; public implementations approximate rather than fully replicate his optimized “harmonic alignment” logic.
- Time-based Fibonacci and complex multi-pattern confluence are under-explored in automated systems.
- Robustness across asset classes (forex vs crypto vs equities) and volatility regimes needs more study.

---

## 6. Practical Starting Points for Implementation

- Start with open-source ZigZag + ratio engines (Python libraries mentioned above or TradingView Pine Script logic).
- Label a high-quality dataset using strict Carney ratios + visual expert review on a subset.
- Train gradient-boosted trees first (strong baseline on tabular ratio features), then explore sequence/CNN models.
- Focus evaluation on out-of-sample PRZ reaction rather than pure pattern-matching accuracy.

---

## Conclusion

The state of the art remains dominated by sophisticated rule-based systems built on ZigZag/pivot detection + precise Fibonacci ratio matching with controlled tolerance, heavily influenced by Scott Carney’s framework. Machine learning is most effective today as a complementary filter, ranking engine, or confirmation layer rather than a pure end-to-end replacement. The highest-leverage path for a new ML model is a hybrid architecture that respects the geometric and ratio constraints while learning which pattern instances are most likely to produce tradable reversals.

This report provides the foundational knowledge needed to design such a system.
