You can also copy the content below:

```markdown
# Harmonic Pattern Detection: ML Starting Points Assessment

**Date**: 21 July 2026

---

## Context

Neurotrader’s project (`neurotrader888/TechnicalAnalysisAutomation`) is primarily **rule-based** (ZigZag-style extremes + Fibonacci ratio matching with a log-error score). It is solid engineering, but not machine learning in the modern sense. The person you spoke to was probably using “ML” loosely, or referring to a different project.

---

## Better Starting Points for an ML-Focused Project

Here are the most realistic options ranked by usefulness for detecting harmonic / Fibonacci XABCD patterns with machine learning:

| Rank | Project / Approach                          | Type                          | Why It’s Useful                                      | Limitations                              | Recommendation |
|------|---------------------------------------------|-------------------------------|------------------------------------------------------|------------------------------------------|--------------|
| 1    | **Hybrid (Best practical path)**            | Rule-based candidates + ML   | Highest chance of success                            | Requires more engineering                | **Strongly recommended** |
| 2    | ChartScanAI (YOLOv8)                        | Computer Vision (Object Detection) | Real deep learning on chart images, open source     | Focused on classical patterns, not harmonics | Good for vision route |
| 3    | Academic CNN/LSTM chart pattern papers      | Sequence / Image models      | Clean research baselines                             | Mostly classical patterns                | Good for learning |
| 4    | Pure end-to-end from scratch                | Custom ML                     | Full control                                         | Very hard (labeling + pivot quality)     | Only if you have strong resources |

---

## 1. Recommended Path: Hybrid System (Most Practical)

This is currently the state-of-the-art practical approach:

- Use a high-quality **rule-based engine** (neurotrader’s code, or a better ZigZag + ratio engine) to generate candidate XABCD structures with moderate tolerance.
- Extract rich features from those candidates (individual ratio errors, leg time ratios, volatility context, volume, multi-timeframe alignment, confluence score, etc.).
- Train an ML model (Gradient Boosting → LSTM/Transformer → or even a small neural net) to:
  - Rank / filter the candidates
  - Predict probability of a successful reversal
  - Predict expected R-multiple or optimal stop placement

This avoids the hardest problem in pure ML (reliably finding the five swing points in noisy data) while still letting machine learning do what it’s good at.

---

## 2. Computer Vision Route – ChartScanAI

**Repo**: [Omar-Karimov/ChartScanAI](https://github.com/Omar-Karimov/ChartScanAI)

- Uses **YOLOv8** (object detection) on rendered chart images.
- Detects classical patterns (triangles, flags, head & shoulders, double tops, etc.).
- Good modern deep-learning codebase with data annotation via Roboflow.

You could adapt this approach to harmonics by:
- Rendering charts
- Drawing or highlighting potential XABCD structures
- Training the detector to find “Gartley-like”, “Bat-like”, etc. regions
- Then running precise Fibonacci measurements only on the detected regions

This is a legitimate pure deep-learning starting point, though it will be less precise on the exact ratios than a hybrid system.

---

## 3. Other Notable Mentions

- **Velay & Daniel (2018)** – “Stock Chart Pattern recognition with Deep Learning” (CNN vs LSTM). Classic academic baseline comparing deep models to hard-coded pattern detectors.
- Various GitHub repos that do classical chart pattern detection with CNNs or LSTMs (search “chart pattern CNN” or “head and shoulders deep learning”).
- Emerging work using Vision-Language Models (VLMs) on chart screenshots — interesting but still early and less precise for geometric constraints.

---

## Bottom Line Recommendation

For a serious project aimed at **harmonic patterns specifically**, I would **not** start from pure end-to-end ML or from ChartScanAI alone.

**Best starting point right now**:

1. Take neurotrader’s (or a similar clean) harmonic detection code as the candidate generator.
2. Improve the pivot detection and feature extraction.
3. Build a supervised ML ranking/filtering layer on top of it.
4. Optionally add a computer-vision branch later for confirmation or multi-pattern detection.

---

Would you like a concrete technical roadmap for the hybrid approach (including suggested features, model choices, and labeling strategy)?
```
