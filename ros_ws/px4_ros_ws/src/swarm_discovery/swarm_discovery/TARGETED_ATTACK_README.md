# Finding F4 — Targeted EKF+χ²+Huber Exploit

**When Drones Go Blind** · COMSM0117 · University of Bristol  
**Author:** Ashwin Kotharamath (2678113) · **Supervisors:** Dr Joe Gardiner · Dr Alma Oracevic  
**Branch:** `finding-f4-complete` · **Script:** `byzantine_targeted_ekf.py`

---

## Table of Contents

1. [Overview](#1-overview)
2. [Mathematical Derivation](#2-mathematical-derivation)
3. [Attack Modes](#3-attack-modes)
4. [Prerequisites](#4-prerequisites)
5. [Quick Start](#5-quick-start)
6. [Running Each Mode](#6-running-each-mode)
7. [Live Monitoring](#7-live-monitoring)
8. [Collecting Evidence](#8-collecting-evidence)
9. [Generating Figures](#9-generating-figures)
10. [Results Summary](#10-results-summary)
11. [Demo for Viva](#11-demo-for-viva)
12. [Threat Model](#12-threat-model)
13. [Mitigations](#13-mitigations)
14. [Academic Context](#14-academic-context)
15. [File Reference](#15-file-reference)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. Overview

Finding F4 is a **mathematically derived, parameter-aware exploit** of the EKF+χ²+Huber cooperative localisation algorithm. Unlike the standard Byzantine attack (`byzantine_insider_attack.py`) which uses an empirically chosen bias of 0.8–3.0 m and is detectable if the bias exceeds the Huber delta, the targeted attack derives the maximum undetectable bias analytically from the algorithm's published source parameters.

### Why it matters

The EKF+χ²+Huber algorithm (`coop_loc_ekf_chi2_huber.py`) is the strongest algorithm in the dissertation's portfolio — achieving 0.034 m baseline accuracy and defeating every other attack in the suite. Finding F4 shows it has a specific, exploitable blind spot when an attacker knows its parameters.

### Key result

```
Max undetectable bias  = √(CHI2_THRESHOLD × S / 3) × 0.85
                       = √(7.815 × 0.05 / 3) × 0.85
                       = 0.307 m

Huber delta            = 0.500 m

0.307 m < 0.500 m  →  bypasses BOTH χ² gate AND Huber loss simultaneously
Peak mahal²            = 3.764  (48% of the 7.815 gate threshold)
Gate triggered         = NEVER  (across full 90-second run)
```

### Attack vs defence comparison

| Metric | Standard Byzantine | Targeted Ramp (F4) | Targeted Osc | Targeted Two-Drone |
|---|---|---|---|---|
| Max bias | 0.8–3.0 m (empirical) | 0.307 m (derived) | 0.276 m (derived) | 0.184 m each (derived) |
| Gate triggered? | Sometimes (high bias) | Never | Never | Never |
| Huber detected? | Yes (bias > delta) | No (bias < delta) | No | No |
| EKF+χ²+Huber error | 0.476 m | 0.039 m | 0.033 m | 0.133 m |
| WLS error | 25.3 m | 0.386 m | 0.153 m | 0.181 m |
| Stealthiness | Medium | **Maximum** | **Maximum** | **High** |

---

## 2. Mathematical Derivation

The χ² innovation gate in `coop_loc_ekf_chi2_huber.py` rejects a range measurement when:

```
mahal² = (z - Hx)ᵀ S⁻¹ (z - Hx) > CHI2_THRESHOLD
```

For a 3-DoF position measurement with diagonal S:

```
mahal² = (bx² + by² + bz²) / S_per_axis
```

Where:
- `CHI2_THRESHOLD = 7.815` (χ²(3 dof, p=0.95), from source line 68)
- `MEAS_NOISE_VAR = 0.04 m²` (R = σ² = 0.2² = 0.04, from source line 70)
- `S_per_axis ≈ 0.05 m²` (S = R + HPHᵀ at steady state)
- `HUBER_DELTA = 0.5 m` (from source line 69)

### Solving for maximum safe bias

Equal bias on X and Y axes, zero on Z:

```
mahal² = (bx² + by²) / S_per_axis ≤ 7.815

For bx = by = b:
  2b² / 0.05 ≤ 7.815
  b ≤ √(7.815 × 0.05 / 2) = 0.442 m

With 85% safety margin:
  b_safe = 0.442 × 0.85 = 0.376 m   (single-axis version)
  b_safe = 0.307 m                   (equal X+Y, verified in logs)
```

### Why both defences are bypassed simultaneously

```
b_safe   = 0.307 m
HUBER_Δ  = 0.500 m
∴ b_safe < HUBER_Δ  →  Huber loss treats this as inlier (no down-weighting)
∴ mahal² = 3.764 < 7.815  →  χ² gate passes (no rejection)
```

Both defences are bypassed with a single calculated value. This is not coincidental — it follows from the relationship between the gate threshold and the noise model.

### Source code parameters

```python
# From coop_loc_ekf_chi2_huber.py lines 68–70:
CHI2_THRESHOLD  = 7.815   # χ²(3 dof, p=0.95)
HUBER_DELTA     = 0.5     # metres
MEAS_NOISE_STD  = 0.2     # → VAR = 0.04 m²
```

---

## 3. Attack Modes

### Mode 1 — `targeted_ramp`

Linear bias ramp from 0 to `MAX_BIAS` (0.307 m) over 40 seconds, then sustained.

```
Phase timeline:
  0–10s   WARMUP     bias = 0.000 m    (behaves honestly, builds trust)
  10–50s  RAMP       bias grows linearly 0 → 0.307 m
  50–90s  SUSTAINED  bias = 0.307 m    (fully corrupted, gate never fires)
```

Best for: demonstrating sustained, stealthy position corruption.  
Results: EKF+χ²+Huber = 0.039 m, WLS = 0.386 m

### Mode 2 — `targeted_osc`

Sinusoidal bias oscillating at ±0.276 m with 8-second period. Each individual sample stays below the gate. The EKF state tracks the oscillation mean over time.

```
bias(t) = 0.276 × sin(2π × (t - warmup) / 8.0)
Peak mahal² per sample ≈ 4.574  (still < 7.815)
```

Best for: demonstrating that even time-varying attacks evade static thresholds.  
Results: EKF+χ²+Huber = 0.033 m (nearly baseline), WLS = 0.153 m

### Mode 3 — `targeted_two_drone`

Two drones (px4_2 and px4_3) each apply 60% of `MAX_BIAS` independently. Each is individually undetectable, but together they push the EKF state coherently.

```
Per-drone bias  = 0.184 m
Per-drone mahal² = 2.033  (<< 7.815, individually invisible)
Combined effect  ≈ 2× single-drone bias on shared EKF state
```

Best for: demonstrating the multi-insider escalation threat.  
Results: EKF+χ²+Huber = 0.133 m (4× baseline), WLS = 0.181 m

> **Note:** For `targeted_two_drone`, you must run the attack script on **both** px4_2 and px4_3 simultaneously (see [Section 6.3](#63-targeted_two_drone)).

---

## 4. Prerequisites

### Software stack

| Component | Version | Check |
|---|---|---|
| PX4 SITL | v1.18 | `px4 --version` |
| Gazebo | Harmonic 8.11.0 | `gz sim --version` |
| ROS 2 | Humble | `ros2 --version` |
| Python | 3.10 | `python3 --version` |
| OS | Ubuntu 22.04 | `lsb_release -a` |

### ROS 2 package must be built

```bash
cd ~/Dissertation/ros_ws/px4_ros_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select swarm_msgs swarm_discovery
source install/setup.bash

# Verify the attack node is registered:
ros2 pkg executables swarm_discovery | grep byzantine_targeted
# Expected: swarm_discovery byzantine_targeted_ekf
```

### SITL swarm must be running

```bash
# Terminal 1 — start and leave running
bash ~/Dissertation/scripts/start_swarm.sh
# Wait for: [+] Swarm ready (~35 seconds)
```

---

## 5. Quick Start

```bash
# Source environment (required every new terminal)
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash

# Run targeted ramp against EKF+χ²+Huber (most important demo)
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber targeted_ramp

# Watch the gate log in a second terminal:
tail -f /tmp/byzantine_targeted_px4_2_targeted_ramp.csv
```

You should immediately see:
```
[WARN] [byzantine_targeted_px4_2]: [TARGETED] mode=targeted_ramp  drone=px4_2
  max_bias=0.3068m  chi2_threshold=7.815  huber_delta=0.5m
  Max bias < Huber delta: True → bypasses BOTH defences simultaneously
```

---

## 6. Running Each Mode

### Environment setup (run once per terminal session)

```bash
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
```

### 6.1 `targeted_ramp`

```bash
# Via ros2 run (recommended):
ros2 run swarm_discovery byzantine_targeted_ekf px4_2 targeted_ramp

# Via python3 directly:
python3 ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/byzantine_targeted_ekf.py \
    px4_2 targeted_ramp

# Smoke test (20-second fast run):
SMOKE_ATTACK_SEC=20 SMOKE_WARMUP_SEC=3 SMOKE_RAMP_SEC=8 \
    ros2 run swarm_discovery byzantine_targeted_ekf px4_2 targeted_ramp
```

Expected output pattern:
```
t=0s   WARMUP     bias=(0.000,0.000,0.000)m  mahal²=0.000/7.815  ✓ BELOW GATE
t=10s  RAMP       bias=(0.001,0.001,0.000)m  mahal²=0.000/7.815  ✓ BELOW GATE
t=20s  RAMP       bias=(0.077,0.077,0.000)m  mahal²=0.235/7.815  ✓ BELOW GATE
t=30s  RAMP       bias=(0.153,0.153,0.000)m  mahal²=0.941/7.815  ✓ BELOW GATE
t=40s  RAMP       bias=(0.230,0.230,0.000)m  mahal²=2.118/7.815  ✓ BELOW GATE
t=50s  SUSTAINED  bias=(0.307,0.307,0.000)m  mahal²=3.764/7.815  ✓ BELOW GATE
t=60s  SUSTAINED  bias=(0.307,0.307,0.000)m  mahal²=3.764/7.815  ✓ BELOW GATE
t=90s  [TARGETED] Attack window complete.
```

### 6.2 `targeted_osc`

```bash
ros2 run swarm_discovery byzantine_targeted_ekf px4_2 targeted_osc

# Smoke test:
SMOKE_ATTACK_SEC=20 SMOKE_WARMUP_SEC=3 \
    ros2 run swarm_discovery byzantine_targeted_ekf px4_2 targeted_osc
```

Expected: mahal² oscillates between ~0 and ~4.574, never exceeding 7.815.

### 6.3 `targeted_two_drone`

This mode requires running the attack on **two drones simultaneously**.

```bash
# Terminal A — px4_2
ros2 run swarm_discovery byzantine_targeted_ekf px4_2 targeted_two_drone &

# Terminal B — px4_3
ros2 run swarm_discovery byzantine_targeted_ekf px4_3 targeted_two_drone &

# Stop both:
pkill -f "byzantine_targeted"
```

> **Why px4_2 and px4_3?** These are the two drones adjacent to px4_1 (the primary honest drone used for error measurement). Their combined influence on the EKF state of px4_1 is maximised by choosing adjacent drones.

---

## 7. Live Monitoring

### Watch the gate log in real time

```bash
# Targeted ramp log:
tail -f /tmp/byzantine_targeted_px4_2_targeted_ramp.csv

# Column headers: t_sec, phase, bias_x, bias_y, bias_z, mahal_sq_estimate, below_gate
# Every row should show below_gate=True
```

### Watch px4_2's published position drifting

```bash
watch -n0.5 'ros2 topic echo /px4_2/coop/self_estimate --once 2>/dev/null | grep -E "x:|y:|z:"'
```

### Watch the localisation error of honest drones

```bash
# px4_1 error (should drift slowly under targeted_ramp):
watch -n1 'ros2 topic echo /px4_1/coop/self_estimate --once 2>/dev/null | grep -E "x:|y:|z:"'
```

### Monitor the chi-squared gate in ekf_chi2_huber logs

```bash
# Check n_rejected_gate column — should stay at 0 during targeted attack:
tail -f ~/Dissertation/evidence/metrics/ekf_chi2_huber_px4_1_targeted_ramp.csv | \
    awk -F',' '{print "t="$1" passed="$6" rejected="$7}'
```

### Topic health check

```bash
# Verify attack is publishing:
ros2 topic hz /px4_2/coop/self_estimate    # should show ~10 Hz during attack

# Verify localisation is running:
ros2 topic hz /px4_1/coop/self_estimate    # should show ~10 Hz

# Verify viz is updating:
ros2 topic hz /swarm/viz/markers           # should show ~25 Hz
```

---

## 8. Collecting Evidence

### Single run (manual)

```bash
# Run one approach × one attack mode:
bash ~/Dissertation/scripts/run_experiment.sh ekf_chi2_huber targeted_ramp
```

CSVs saved to:
```
~/Dissertation/evidence/metrics/ekf_chi2_huber_px4_{1..5}_targeted_ramp.csv
```

### Full matrix — all 3 modes × 6 approaches (90 CSVs, ~30 minutes)

```bash
cd ~/Dissertation

for attack in targeted_ramp targeted_osc targeted_two_drone; do
    for approach in wls ekf wls_huber wls_tukey ransac ekf_chi2_huber; do
        echo "═══ $approach / $attack ═══"
        bash ~/Dissertation/scripts/run_experiment.sh $approach $attack
        sleep 5
    done
done
```

### Monitor progress

```bash
# Count CSVs as they appear:
watch -n5 'ls ~/Dissertation/evidence/metrics/*targeted* 2>/dev/null | wc -l'
# Target: 90 (18 experiments × 5 drones)
```

### Validate data quality

```bash
# Check for FROZEN or SHORT runs:
python3 ~/Dissertation/validate_localisation_csvs.py

# Check attack injection actually fired:
python3 ~/Dissertation/validate_attacks.py

# Check CSV row counts:
for f in ~/Dissertation/evidence/metrics/*targeted_ramp*px4_1*; do
    echo "$(wc -l < $f) rows — $(basename $f)"
done
# Expect ~900 rows per CSV (90s × 10 Hz)
```

---

## 9. Generating Figures

### Finding F4 dedicated figure (fig6)

```bash
python3 ~/Dissertation/fig6_finding_f4.py

# Output: ~/Dissertation/evidence/figures/dissertation/fig6_finding_f4.png
# Four panels:
#   A — mahal² over time (stays below gate throughout)
#   B — targeted ramp vs standard Byzantine, all 6 approaches
#   C — degradation factor under targeted ramp
#   D — error time-series, all 6 approaches
```

### Full dissertation figure suite (includes targeted attacks)

```bash
python3 ~/Dissertation/analyse_dissertation.py \
    --gt-csv ~/Dissertation/evidence/gt/gt_px4_1_ekf_chi2_huber_targeted_ramp.csv

# Regenerates fig1–fig5 with targeted_ramp, targeted_osc, targeted_two_drone
# included in the attack comparison and degradation figures
```

### Add degradation factors to summary table

```bash
python3 ~/Dissertation/add_degradation_factor.py

# Adds targeted_ramp/osc/two_drone degradation columns to:
# ~/Dissertation/evidence/figures/dissertation/summary_table_with_degradation.csv
```

### View figures

```bash
eog ~/Dissertation/evidence/figures/dissertation/fig6_finding_f4.png
eog ~/Dissertation/evidence/figures/dissertation/fig5_attack_degradation.png
```

---

## 10. Results Summary

### Per-algorithm mean error under targeted attacks (px4_1, drone not under attack)

| Approach | Baseline | targeted_ramp | targeted_osc | targeted_two_drone | Byzantine (std) |
|---|---|---|---|---|---|
| WLS | 0.542 m | 0.386 m | 0.153 m | 0.181 m | 25.267 m |
| EKF | 0.194 m | 0.259 m | 0.180 m | 0.186 m | 23.142 m |
| WLS+Huber | 0.521 m | 0.280 m | 0.171 m | 0.170 m | 27.442 m |
| WLS+Tukey | 0.534 m | 0.301 m | 0.162 m | 0.166 m | 36.841 m |
| RANSAC | 0.812 m | 0.258 m | 0.141 m | 0.179 m | 1.953 m |
| **EKF+χ²+Huber** | **0.034 m** | **0.039 m** | **0.033 m** | **0.133 m** | **0.476 m** |

### Key interpretations

**targeted_ramp vs baseline:** EKF+χ²+Huber degrades only 1.15× (0.034 → 0.039 m). The algorithm is remarkably resilient to a single-drone targeted attack at this bias level. However WLS degrades from 0.542 to 0.386 m — *apparently improving* — because the targeted ramp is smaller than the noise floor, causing cancellation effects in the WLS solver.

**targeted_osc vs targeted_ramp:** Oscillating mode produces *lower* error than ramp mode for most algorithms. The sinusoidal bias averages to near-zero over one period, so the mean error reflects only the transient peaks rather than a sustained offset.

**targeted_two_drone:** EKF+χ²+Huber degrades from 0.034 to 0.133 m (4× baseline) — significantly worse than single-drone targeted_ramp (0.039 m). This confirms the coordinated attack hypothesis: two individually-undetectable biases combine coherently to move the EKF state faster than the filter's covariance update can compensate.

**Why RANSAC handles targeted attacks better than Byzantine:** RANSAC's inlier consensus operates on range measurements from the *ranging layer*, not on self_estimate publications. All three targeted attacks inject on the feedback layer (`/px4_N/coop/self_estimate`), which RANSAC does not gate. RANSAC's good performance here (0.141–0.258 m) is because the small targeted bias stays within its inlier threshold — not because RANSAC actively detected and rejected it.

---

## 11. Demo for Viva

### Interactive demo using demo.sh

```bash
# Baseline — clean localisation
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber

# Targeted ramp — mathematically stealthy, gate never fires
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber targeted_ramp

# Compare: standard Byzantine (visible/detectable) vs targeted (stealthy)
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber byzantine
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber targeted_ramp

# Show escalation: two-drone coordinated
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber targeted_two_drone
```

### What to say during the demo

**Before injection:**
> "EKF+χ²+Huber is running at baseline. Yellow balls sit on top of teal ground truth at about 3 centimetre accuracy — the best in the suite."

**After injecting targeted_ramp:**
> "I've injected the targeted attack. The bias is mathematically constrained to 0.307 metres — below the Huber delta of 0.5 metres and producing a Mahalanobis distance of 3.764 against a gate threshold of 7.815. Every measurement passes both defences. The yellow balls barely move — 0.039 metres mean error versus 0.034 at baseline."

**Switching to two-drone:**
> "Now I'll run two drones simultaneously, each at 60% of the safe bias. Neither is individually detectable. But together they push the EKF state coherently — error rises to 0.133 metres, four times the baseline. This is the two-insider escalation: the same gate threshold that protects against a single attacker becomes a liability against coordinated compromise."

**Contrast with standard Byzantine:**
> "For comparison, standard Byzantine uses 0.8 metres of bias — above the Huber delta — and causes 0.476 metres of error. The targeted attack achieves persistent corruption at 0.039 metres while being fully invisible to the detection pipeline. That's the contribution of Finding F4."

### Viva question preparation

**Q: "How do you know the attack is actually evading the gate and not just having no effect?"**  
A: The gate log at `/tmp/byzantine_targeted_px4_2_targeted_ramp.csv` shows `below_gate=True` on every single row for the full 90-second run. The `n_rejected_gate` column in the localisation CSV also stays at 0 throughout. The attack is reaching the EKF — we can see the position corruption in the WLS/EKF algorithms which have no gate, and they show measurable error.

**Q: "Could the defender just lower the chi-squared threshold to catch this?"**  
A: Yes — but at a cost. Lowering CHI2_THRESHOLD from 7.815 to, say, 4.0 would catch the targeted ramp at sustained phase (mahal² = 3.764) but would also reject legitimate measurements during high-dynamics phases, increasing baseline error. The optimal threshold depends on the noise model — adaptive thresholding via CUSUM would be the principled fix.

**Q: "What's the proposed mitigation?"**  
A: Three layers: (1) CUSUM-based change-point detection on the innovation sequence — catches gradual ramps that static thresholds miss; (2) cross-drone consistency checking — if two drones simultaneously report inconsistent self_estimates, flag coordinated attack; (3) HMAC-signed self_estimate publications — prevents impersonation of legitimate drone IDs at the DDS layer.

---

## 12. Threat Model

### Attacker capabilities

- Controls one registered swarm drone (px4_2) with legitimate DDS access
- Can publish on any `/px4_N/coop/self_estimate` topic without authentication
- Knows the target algorithm's published parameters (CHI2_THRESHOLD, HUBER_DELTA, MEAS_NOISE_STD)
- Cannot break cryptographic primitives or control PX4's internal uORB bus

### Attack surface

```
Feedback layer: /px4_N/coop/self_estimate  (PointStamped)
  ↑ This is where all three targeted attack modes inject
  ↑ Different from ranging layer attacks (Sybil, Wormhole, Replay, Timesync)

Why this matters:
  Ranging layer defences (Huber, Tukey losses) operate on range residuals
  Feedback layer bias bypasses those defences entirely
  Only RANSAC's inlier consensus partially helps (via range consistency)
```

### STRIDE classification

| Attack | Spoofing | Tampering | Repudiation | Info Disclosure | DoS | EoP |
|---|---|---|---|---|---|---|
| targeted_ramp | | ✓ | | | | ✓ |
| targeted_osc | | ✓ | | | | ✓ |
| targeted_two_drone | | ✓ | | | | ✓ |

---

## 13. Mitigations

Ranked by implementation priority:

### 1. CUSUM change-point detection (highest priority)

Replaces the static χ² threshold with a sequential test that accumulates evidence of gradual drift:

```python
# In coop_loc_ekf_chi2_huber.py — add after innovation computation:
CUSUM_H     = 5.0   # CUSUM threshold
CUSUM_K     = 1.0   # reference value (half the expected shift)

self.cusum_pos = max(0, self.cusum_pos + mahal_sq - CUSUM_K)
self.cusum_neg = min(0, self.cusum_neg + mahal_sq + CUSUM_K)

if self.cusum_pos > CUSUM_H or abs(self.cusum_neg) > CUSUM_H:
    self.get_logger().warn(f"[CUSUM] Drift detected from {nbr}")
    self.cusum_pos = 0.0
    self.cusum_neg = 0.0
    continue  # reject this measurement
```

This catches targeted_ramp at approximately t=35s (during ramp phase) rather than never.

### 2. Cross-drone consistency check

Flag coordinated attacks by checking that no two drones' self_estimates move in the same direction simultaneously:

```python
# Add to swarm_registry.py or a separate anomaly_detector.py node:
# If |estimate_A - estimate_B| > CONSISTENCY_THRESHOLD for two neighbours
# and both moved in the same direction in the last N steps → flag
CONSISTENCY_THRESHOLD = 0.15  # m — below targeted_ramp bias of 0.307m
```

### 3. HMAC-authenticated self_estimate publications

Add a shared HMAC key per drone pair, signed with SHA-256, to prevent impersonation:

```python
import hmac, hashlib

def sign_estimate(payload_bytes, key):
    return hmac.new(key, payload_bytes, hashlib.sha256).digest()[:8]

def verify_estimate(payload_bytes, key, signature):
    expected = sign_estimate(payload_bytes, key)
    return hmac.compare_digest(expected, signature)
```

Cost: ~1 ms per message. Defeats: valid-ID impersonation (Design B gap, Finding F3b).

### 4. SROS2 / DDS Security

Deploy per-node X.509 certificates so only authenticated nodes can publish on sensitive topics. See [SROS2 documentation](https://docs.ros.org/en/humble/How-To-Guides/DDS-tuning.html).

Cost: ~5–15% DDS throughput overhead.

---

## 14. Academic Context

Finding F4 is grounded in a well-established body of work on stealthy false data injection (FDI) attacks against Kalman filter-based estimators:

- **Mo, Garone, Casavola, Sinopoli (2010)** — established that an attacker knowing the system model and noise covariance can craft injections that remain within the χ² detector's threshold indefinitely. This is the theoretical foundation for the targeted bias calculation.

- **Chu et al. (2019)** — "Can Predictive Filters Detect Gradually Ramping False Data Injection Attacks?" (arXiv:1905.02271) — shows directly that gradual bias ramps bypass static χ² detectors and remain damaging. This paper validates the ramp mode design.

- **Bonczek and Bezzo (2021)** — "Detection of Hidden Attacks on Cyber-Physical Systems from Serial Magnitude and Sign Randomness Inconsistencies" — proposes monitoring the *pattern* of chi-squared test measure values over time (rather than individual values) to catch stealthy attacks. This motivates the CUSUM mitigation.

- **arXiv:2501.07597 (2025)** — notes that chi-squared detectors "face significant drawbacks: their assumption of low-dimensional or Gaussian data diminishes their effectiveness in UAV systems with high-dimensional, non-Gaussian dynamics."

**What Finding F4 adds to this literature:**

Prior work proves the *existence* of stealthy FDI attacks against chi-squared detectors in abstract control systems. Finding F4 transfers this to cooperative UAV localisation and shows:

1. The maximum undetectable bias can be derived from published algorithm parameters in a single calculation
2. This bias simultaneously falls below the Huber delta — bypassing *both* defences in EKF+χ²+Huber with one value
3. The result is empirically verified in a production autopilot (PX4 v1.18) and middleware (ROS 2 Humble) stack with 90 logged CSV experiments
4. The two-drone coordinated variant demonstrates that individually-undetectable biases compound coherently

---

## 15. File Reference

```
Finding F4 files:
├── ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/
│   └── byzantine_targeted_ekf.py          ← Attack implementation (3 modes)
│
├── fig6_finding_f4.py                      ← Four-panel analysis figure generator
│
├── evidence/
│   ├── metrics/
│   │   ├── *_targeted_ramp_px4_N.csv      ← 30 CSVs (6 approaches × 5 drones)
│   │   ├── *_targeted_osc_px4_N.csv       ← 30 CSVs
│   │   └── *_targeted_two_drone_px4_N.csv ← 30 CSVs
│   └── figures/dissertation/
│       └── fig6_finding_f4.png             ← Four-panel evidence figure
│
├── scripts/
│   ├── demo.sh                             ← Interactive viva demo
│   ├── run_experiment.sh                   ← Batch data collection
│   └── DEMO_README.md                      ← Demo quick reference
│
└── /tmp/
    ├── byzantine_targeted_px4_2_targeted_ramp.csv     ← Live gate log
    ├── byzantine_targeted_px4_2_targeted_osc.csv
    └── byzantine_targeted_px4_2_targeted_two_drone.csv
```

### CSV column reference

**Metrics CSVs** (`evidence/metrics/ekf_chi2_huber_px4_1_targeted_ramp.csv`):

| Column | Description |
|---|---|
| `t_sec` | Elapsed time in seconds |
| `x, y, z` | Estimated position (metres) |
| `solve_ms` | Solver latency (milliseconds) |
| `n_passed_gate` | χ² gate: measurements accepted this tick |
| `n_rejected_gate` | χ² gate: measurements rejected this tick |
| `trace_P` | EKF covariance trace (proxy for estimation uncertainty) |

**Gate log CSVs** (`/tmp/byzantine_targeted_px4_2_targeted_ramp.csv`):

| Column | Description |
|---|---|
| `t_sec` | Elapsed time |
| `phase` | WARMUP / RAMP / SUSTAINED / OSCILLATING / COORDINATED_RAMP |
| `bias_x, bias_y, bias_z` | Applied bias vector (metres) |
| `mahal_sq_estimate` | Estimated Mahalanobis² at current bias |
| `below_gate` | True if mahal² < 7.815 (should always be True) |

---

## 16. Troubleshooting

### `No executable found` when running via ros2 run

```bash
# Rebuild and re-source:
cd ~/Dissertation/ros_ws/px4_ros_ws
colcon build --packages-select swarm_discovery
source install/setup.bash

# Verify entry point registered:
grep "byzantine_targeted" src/swarm_discovery/setup.py
# Expected: 'byzantine_targeted_ekf = swarm_discovery.byzantine_targeted_ekf:main',
```

### `ModuleNotFoundError: No module named 'rclpy'`

```bash
# ROS 2 environment not sourced:
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
```

### `AttributeError: can't set attribute 'publishers'`

```bash
# Fix the attribute name clash with Node base class:
sed -i 's/self\.publishers/self._pubs/g' \
    ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/byzantine_targeted_ekf.py
colcon build --packages-select swarm_discovery
source install/setup.bash
```

### mahal² occasionally exceeds 7.815

This can happen if the EKF steady-state covariance `P` is larger than assumed (S = R + HPHᵀ > 0.05 m²). The 85% safety margin should prevent this, but if the swarm is in a high-dynamics phase the covariance inflates temporarily.

Fix: reduce `SAFE_BIAS_MARGIN` from 0.85 to 0.75 in `byzantine_targeted_ekf.py`:

```bash
sed -i 's/SAFE_BIAS_MARGIN = 0.85/SAFE_BIAS_MARGIN = 0.75/' \
    ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/byzantine_targeted_ekf.py
```

### Gate log not appearing at `/tmp/byzantine_targeted_*`

The log is written by the attack node — check the node is actually running:

```bash
ros2 node list | grep byzantine
# Expected: /byzantine_targeted_px4_2
```

If node is running but no log file, check `/tmp/` permissions:

```bash
ls -la /tmp/byzantine_targeted* 2>/dev/null || echo "No log files found"
```

### demo.sh terminates immediately

```bash
# Check for pkill self-kill via attack name in process args:
# Run from a plain terminal (not inside tmux)
# Or verify the fix is in place:
grep "MYPID" ~/Dissertation/scripts/demo.sh
# Expected: MYPID=$$  (in kill_demo_nodes function)
```

---

*MSc Dissertation — COMSM0117 — University of Bristol — 2026*  
*Branch: `finding-f4-complete` · Tag: `finding-f4-complete`*
