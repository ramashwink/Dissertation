# When Drones Go Blind
### Security Analysis of Cooperative Localisation in GPS-Denied UAV Swarms

**MSc Cyber Security & Infrastructure Security — COMSM0117**
University of Bristol · Bristol Cyber Security Group
Ashwin Kotharamath · Registration 2678113 · se25272@bristol.ac.uk
Supervisors: Dr Joe Gardiner · Dr Alma Oracevic
Submission: 4 September 2026

---

## Overview

This repository contains the full implementation, attack suite, mitigation algorithms, and analysis pipeline for an empirical security study of cooperative swarm localisation in GPS-denied environments.

A drone swarm navigating indoors without GPS must share LiDAR range measurements with its neighbours to estimate its own position. This is a **trust-based system** — a single rogue insider can corrupt every other drone's view of where it is. This project asks: *how bad can it get, and what can be done about it?*

---

## Research Questions

**RQ1** — What are the primary security vulnerabilities in cooperative localisation algorithms used in GPS-denied drone swarm environments?

**RQ2** — What are the fundamental trade-offs between security, positioning accuracy, communication efficiency, and computational cost when mitigating those vulnerabilities?

---

## Repository Structure

```
Dissertation/
├── ros_ws/px4_ros_ws/
│   └── src/
│       ├── swarm_msgs/                    # Custom ROS 2 message types
│       │   ├── msg/SwarmMember.msg
│       │   ├── msg/SwarmRegistry.msg
│       │   ├── srv/RegisterDrone.srv
│       │   └── srv/Keepalive.srv
│       └── swarm_discovery/
│           └── swarm_discovery/
│               ├── ground_truth_demux.py          # gz-transport → ROS 2 GT
│               ├── inter_drone_ranging.py         # Simulated LiDAR ranging
│               ├── swarm_registry.py              # Design A: topic-based
│               ├── swarm_registry_service.py      # Design B: allowlist
│               ├── swarm_heartbeat.py
│               ├── swarm_client.py
│               ├── cooperative_localisation_dynamic.py   # WLS baseline
│               ├── cooperative_localisation_ekf.py       # EKF baseline
│               ├── coop_loc_wls_huber.py          # WLS + Huber (approach 3)
│               ├── coop_loc_wls_tukey.py          # WLS + Tukey (approach 4)
│               ├── coop_loc_ransac.py             # RANSAC (approach 5)
│               ├── coop_loc_ekf_chi2_huber.py     # EKF + χ² + Huber (approach 6)
│               ├── coop_loc_logger.py             # External CSV logger for WLS/EKF
│               ├── sybil_registry_attack.py       # Sybil attack
│               ├── sybil_service_attack.py        # Sybil against Design B
│               ├── replay_attack.py               # Replay attack
│               ├── wormhole_attack.py             # Wormhole attack
│               ├── ekf_attack_logger.py           # WLS vs EKF comparison logger
│               └── swarm_viz.py                   # RViz2 + Gazebo visualisation
├── scripts/
│   ├── start_swarm.sh                    # Launch 5-drone PX4 SITL
│   ├── launch_wls.sh                     # WLS full stack
│   ├── launch_ekf.sh                     # EKF full stack
│   ├── launch_mitigation.sh              # Any mitigation approach
│   ├── launch_stack_service.sh           # Design B (allowlist registry)
│   ├── run_experiment.sh                 # Single experiment runner
│   └── run_all_experiments.sh            # Full 6×4 matrix runner
├── analyse_dissertation.py               # Main analysis + figure generator
├── analyse_all_approaches.py             # Per-approach analyser
├── extract_ground_truth.py               # Gazebo GT → CSV (x500_N → px4_N)
└── evidence/
    ├── metrics/                          # Per-drone per-approach CSV logs
    ├── gt/                               # Ground truth CSVs
    └── figures/dissertation/             # Generated dissertation figures
```

---

## Branches

| Branch | Content |
|---|---|
| `main` | Stable baseline — WLS cooperative localisation, 3-drone testbed |
| `attack-experiments` | Sybil, Replay, Wormhole attack validation on 3 drones |
| `five-drone-experiments` | 5-drone testbed, WLS + EKF baseline comparison |
| `mitigation-experiments` | **Current** — 6 localisation approaches + full attack/mitigation matrix |

---

## Simulation Stack

| Component | Version |
|---|---|
| PX4 SITL | v1.18 |
| Gazebo | Harmonic 8.11.0 |
| ROS 2 | Humble |
| Micro-XRCE-DDS-Agent | Built from source |
| Python | 3.10 |
| OS | Ubuntu 22.04 (WSL2 / Windows 11) |

---

## Testbed Architecture

5-drone swarm in a GPS-denied Gazebo world. Each drone runs PX4 SITL. The cooperative localisation stack is a novel research artefact — it does not exist in stock PX4.

```
Gazebo (x500_1..x500_5)
    ↓ gz-transport
ground_truth_demux.py → /sim/ground_truth/px4_N/pose
    ↓
inter_drone_ranging.py → /px4_N/coop/range_to/px4_M  (LiDAR noise σ=0.05m)
    ↓
swarm_registry.py + swarm_heartbeat.py × 5  (Design A)
    ↓
[localisation algorithm] × 5 → /px4_N/coop/self_estimate
    ↓
extract_ground_truth.py → evidence/gt/gt_px4_N.csv
analyse_dissertation.py → evidence/figures/dissertation/
```

---

## Localisation Algorithms

| # | Approach | Script | Key mechanism |
|---|---|---|---|
| 1 | WLS | `cooperative_localisation_dynamic.py` | Levenberg-Marquardt, L2 loss |
| 2 | EKF | `cooperative_localisation_ekf.py` | 6-state EKF, constant-velocity |
| 3 | WLS + Huber | `coop_loc_wls_huber.py` | Huber loss, down-weights outliers |
| 4 | WLS + Tukey | `coop_loc_wls_tukey.py` | Bisquare IRLS, hard-zeros outliers |
| 5 | RANSAC | `coop_loc_ransac.py` | Random consensus, ignores minority |
| 6 | **EKF + χ² + Huber** | `coop_loc_ekf_chi2_huber.py` | χ² innovation gate + Huber update |

All mitigation nodes (3–6) write per-drone CSV logs to `evidence/metrics/` with columns: `t_sec, x, y, z, solve_ms`.

---

## Attacks Implemented

| Attack | Script | Mechanism | STRIDE |
|---|---|---|---|
| Sybil | `sybil_registry_attack.py` | Ghost heartbeats + fake `self_estimate` topics | Spoofing, Tampering |
| Replay | `replay_attack.py` | 5-second delayed range measurements | Spoofing, DoS |
| Wormhole | `wormhole_attack.py` | px4_1↔px4_5 range shrunk to 5% of true distance | Tampering, EoP |

### Key Empirical Findings (earlier branches)

- **Sybil**: peak WLS error 0.70 m (5-drone)
- **Replay**: peak error ~9.45 m
- **Wormhole**: peak error 83.1 m (5-drone) — largest attack impact
- **Stale timestamp**: PX4 accepted ~56-year-old timestamps with zero freshness validation
- **Design B finding**: allowlist blocks Sybil (unknown IDs) but not impersonation (valid ID reuse)

---

## Baseline Results (mitigation-experiments branch)

Measured on px4_1 at hover, no attack, against Gazebo ground truth:

| Approach | Mean error (m) | Peak error (m) | RMSE (m) | Solve time (ms) |
|---|---|---|---|---|
| **WLS + Huber** | **0.67** | **1.17** | **0.72** | **1.73** |
| WLS | 1.89 | 2.40 | 1.89 | — |
| EKF + χ² + Huber | 1.99 | 2.56 | 2.03 | 0.91 |
| WLS + Tukey | 2.10 | 2.95 | 2.10 | 5.83 |
| EKF | 3.35 | 3.38 | 3.35 | — |
| RANSAC | 4.74 | 5.03 | 4.75 | 20.72 |

---

## Quick Start

### Prerequisites

```bash
# PX4 SITL, Gazebo Harmonic, ROS 2 Humble, Micro-XRCE-DDS-Agent
# All installed on Ubuntu 22.04 lab machine

# Build the package
cd ~/Dissertation/ros_ws/px4_ros_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select swarm_msgs swarm_discovery
source install/setup.bash
```

### Run a single experiment

```bash
# Terminal 1 — start SITL (leave running)
bash ~/Dissertation/scripts/start_swarm.sh

# Terminal 2 — run one complete experiment (launch → 90s → kill → save CSVs)
bash ~/Dissertation/scripts/run_experiment.sh wls_huber baseline
bash ~/Dissertation/scripts/run_experiment.sh ekf_chi2_huber sybil

# Analyse
python3 ~/Dissertation/analyse_dissertation.py \
    --gt-csv ~/Dissertation/evidence/gt/gt_px4_1.csv
```

### Run the full experiment matrix (~48 min unattended)

```bash
bash ~/Dissertation/scripts/run_all_experiments.sh
```

### Supported approaches and attacks

```bash
# Approaches: wls | ekf | wls_huber | wls_tukey | ransac | ekf_chi2_huber
# Attacks:    baseline | sybil | replay | wormhole

bash ~/Dissertation/scripts/run_experiment.sh <approach> <attack>
```

---

## Analysis

```bash
# Generate all 5 dissertation figures + summary table
python3 ~/Dissertation/analyse_dissertation.py \
    --gt-csv ~/Dissertation/evidence/gt/gt_px4_1.csv

# Output: ~/Dissertation/evidence/figures/dissertation/
#   fig1_baseline_comparison.png    — accuracy per algorithm
#   fig2_attack_comparison.png      — all approaches under each attack
#   fig3_rq2_tradeoff.png           — error vs compute cost (RQ2)
#   fig4_solve_latency.png          — solve time over time
#   fig5_attack_degradation.png     — error increase under attack
#   summary_table.csv               — full numeric results
```

---

## Key Design Decisions

**Full relative-vector residuals** (not range-only trilateration) are required for WLS to avoid rank deficiency with collinear anchors. This was a critical fix achieving sub-centimetre convergence.

**Per-pair independent publishing** in `inter_drone_ranging.py` replaced an all-or-nothing gate that caused cascade dropout when any single drone's ground truth was stale.

**BEST_EFFORT QoS** is required for all PX4 `/fmu/out` topics — RELIABLE subscribers receive nothing and fail silently.

**gz-transport bypasses ros_gz_bridge** for ground truth extraction because the bridge strips entity names from `Pose_V → TFMessage` conversions. Model names in Gazebo are `x500_1..x500_5`, mapped to `px4_1..px4_5` by `extract_ground_truth.py`.

---

## References

- Patwari et al., "Locating the nodes," IEEE SPM 2005
- Wymeersch et al., "Cooperative localization in wireless networks," IEEE 2009
- Roumeliotis & Bekey, "Distributed multi-robot localization," IEEE T-RO 2002
- Newsome et al., "The Sybil attack in sensor networks," IPSN 2004
- Hu, Perrig & Johnson, "Wormhole attacks in wireless networks," IEEE JSAC 2006
- Choe & Kang, "ECC-Based Authentication for Military IoD," IEEE Access 2025
- Cordill et al., "Comprehensive Survey of Security and Privacy in UAV Systems," IEEE Access 2025

---

*MSc Dissertation — COMSM0117 — University of Bristol — 2026*
