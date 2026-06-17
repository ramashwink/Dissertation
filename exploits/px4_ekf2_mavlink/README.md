# When Drones Go Blind

**Security Analysis of Cooperative Localisation in GPS-Denied UAV Swarms**

MSc Cyber Security & Infrastructure Security — COMSM0117  
University of Bristol · Bristol Cyber Security Group  
Ashwin Kotharamath · Registration 2678113 · se25272@bristol.ac.uk  
Supervisors: Dr Joe Gardiner · Dr Alma Oracevic  
Submission: 4 September 2026

---

## What this project does

A drone swarm navigating indoors without GPS must share range measurements with its neighbours to estimate its own position — a trust-based system with no built-in authentication. This project asks: *how bad can it get, and what can be done about it?*

Six cooperative localisation algorithms are compared under eight attacks in a 5-drone PX4 SITL / Gazebo Harmonic testbed. Every component — ranging, registry, localisation, attacks, logging, and visualisation — is a novel research artefact built on ROS 2 Humble.

**Research questions**

- **RQ1** — What are the primary security vulnerabilities in cooperative localisation algorithms used in GPS-denied UAV swarm environments?
- **RQ2** — What are the fundamental trade-offs between security, accuracy, communication efficiency, and computational cost when mitigating those vulnerabilities?

---

## System architecture

```
┌─────────────────────────────────────────────────────────────────┐
│               PX4 SITL + Gazebo Harmonic                        │
│         5 × x500 drones · ROS 2 Humble · XRCE-DDS              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ gz-transport
                           ▼
                  ground_truth_demux.py
                           │
              /sim/ground_truth/px4_N/pose
                           │
            ┌──────────────┴──────────────┐
            │                             │
            ▼                             ▼
  inter_drone_ranging.py        swarm_registry.py
  (LiDAR noise σ=0.05 m)       swarm_heartbeat.py × 5
            │                             │
  /px4_N/coop/range_to/px4_M    /swarm/registry
            │                             │
            └──────────────┬──────────────┘
                           ▼
          ┌────────────────────────────────────┐
          │     Cooperative localisation        │
          │  WLS · EKF · WLS+Huber · WLS+Tukey │
          │  RANSAC · EKF+χ²+Huber (proposed)  │
          └────────────────┬───────────────────┘
                           │
              /px4_N/coop/self_estimate
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
         swarm_viz.py           coop_loc_logger.py
              │                         │
    ┌─────────┴──────┐          evidence/metrics/
    ▼                ▼                  │
  RViz2         Gazebo GUI      analyse_dissertation.py
  MarkerArray   /marker API             │
                                evidence/figures/dissertation/
```

### Attack injection points

Six of the eight attacks inject into the **ranging layer** (`/px4_N/coop/range_to/px4_M`) — they corrupt the range measurements before they reach any localisation algorithm. Byzantine is distinct: it poisons the **cooperative feedback layer** (`/px4_N/coop/self_estimate`), which is why robust range-residual methods (Huber, Tukey) that defeat wormhole cannot defend against it.

```
Ranging layer attacks (①–⑥):          Feedback layer attack (⑦):

  Sybil          → ghost anchor IDs      Byzantine insider → poison
  Sybil-consistent → plausible ghost       /px4_N/coop/self_estimate
  Replay         → stale range inject      (different attack surface —
  Replay-gradual → slow temporal drift      WLS+Tukey cannot help here)
  Wormhole       → compressed range tunnel
  Timesync       → clock skew → range bias
```

> **Security note:** The swarm registry operates at ROS 2 application layer. ROS 2's underlying DDS transport has no authentication — any node can publish on any topic, bypassing the registry entirely. This is the root cause of the Design B impersonation vulnerability and motivates HMAC/SROS2 as future work.

---

## Repository structure

```
Dissertation/
├── ros_ws/px4_ros_ws/src/
│   ├── swarm_msgs/                        # Custom ROS 2 message types
│   │   ├── msg/SwarmMember.msg
│   │   ├── msg/SwarmRegistry.msg
│   │   ├── srv/RegisterDrone.srv
│   │   └── srv/Keepalive.srv
│   └── swarm_discovery/swarm_discovery/
│       │
│       ├── ── Infrastructure ──
│       ├── ground_truth_demux.py          # gz-transport → ROS 2 ground truth
│       ├── inter_drone_ranging.py         # Simulated LiDAR ranging (σ=0.05 m)
│       ├── swarm_registry.py              # Design A: topic-based discovery
│       ├── swarm_registry_service.py      # Design B: allowlist (srv-based)
│       ├── swarm_heartbeat.py             # Per-drone heartbeat publisher
│       ├── swarm_client.py                # Design B client (srv registration)
│       ├── swarm_viz.py                   # RViz2 + Gazebo marker publisher
│       ├── coop_loc_logger.py             # CSV logger (all approaches)
│       │
│       ├── ── Localisation algorithms ──
│       ├── cooperative_localisation_dynamic.py   # Approach 1: WLS baseline
│       ├── cooperative_localisation_ekf.py       # Approach 2: EKF baseline
│       ├── coop_loc_wls_huber.py                 # Approach 3: WLS + Huber
│       ├── coop_loc_wls_tukey.py                 # Approach 4: WLS + Tukey
│       ├── coop_loc_ransac.py                    # Approach 5: RANSAC
│       ├── coop_loc_ekf_chi2_huber.py            # Approach 6: EKF+χ²+Huber ★
│       │
│       └── ── Attack scripts ──
│           ├── sybil_registry_attack.py          # Sybil (Design A)
│           ├── sybil_consistent_attack.py        # Sybil-consistent
│           ├── sybil_service_attack.py           # Sybil (Design B)
│           ├── replay_attack.py                  # Replay (5 s delay)
│           ├── replay_attack_gradual.py          # Replay-gradual (slow drift)
│           ├── wormhole_attack.py                # Wormhole (5% range)
│           ├── timesync_attack.py                # Timesync (clock skew)
│           └── byzantine_insider_attack.py       # Byzantine (feedback poison)
│
├── scripts/
│   ├── start_swarm.sh                     # Launch 5-drone PX4 SITL + Gazebo
│   ├── start_lab.sh                       # Lab machine startup (full env)
│   ├── launch_stack_service.sh            # Full ROS 2 stack (Design B)
│   ├── launch_wls.sh                      # WLS-only stack
│   ├── launch_ekf.sh                      # EKF-only stack
│   ├── launch_mitigation.sh               # Any mitigation approach
│   ├── run_experiment.sh                  # Single approach × attack run
│   ├── cleanup_swarm.sh                   # Verified process cleanup
│   └── rerun_missing.sh                   # Targeted re-run of missing CSVs
│
├── analyse_dissertation.py                # Main analysis + figure generator
├── analyse_all_approaches.py              # Per-approach deep analysis
├── split_attack_figures.py                # Split catastrophic/moderate figs
├── fig3_rq2_tradeoff_patch.py             # Patched RQ2 tradeoff figure
├── add_degradation_factor.py              # Adds degradation_factor to CSV
├── validate_attacks.py                    # Per-attack injection validation
├── validate_localisation_csvs.py          # Detects FROZEN/SHORT runs
├── extract_ground_truth.py                # Gazebo GT → CSV
└── evidence/
    ├── metrics/                           # Per-drone per-approach CSVs
    │   └── {approach}_{attack}_px4_N.csv
    ├── gt/                                # Ground truth CSVs
    │   └── gt_px4_N_{approach}_{attack}.csv
    └── figures/dissertation/              # Generated figures
        ├── fig1_baseline_comparison.png
        ├── fig2a_catastrophic_attacks_px4_1.png
        ├── fig2b_moderate_attacks_px4_1.png
        ├── fig3_rq2_tradeoff.png
        ├── fig4_solve_latency.png
        ├── fig5_attack_degradation.png
        └── summary_table_with_degradation.csv
```

---

## Simulation stack

| Component | Version |
|---|---|
| PX4 SITL | v1.18 |
| Gazebo | Harmonic 8.11.0 |
| ROS 2 | Humble |
| Micro-XRCE-DDS-Agent | Built from source |
| Python | 3.10 |
| OS | Ubuntu 22.04 (WSL2 / Windows 11) |

---

## Localisation algorithms

| # | Approach | Script | Key mechanism |
|---|---|---|---|
| 1 | WLS | `cooperative_localisation_dynamic.py` | Levenberg-Marquardt, L2 loss |
| 2 | EKF | `cooperative_localisation_ekf.py` | 6-state EKF, constant-velocity |
| 3 | WLS + Huber | `coop_loc_wls_huber.py` | Huber loss, soft outlier down-weight |
| 4 | WLS + Tukey | `coop_loc_wls_tukey.py` | Bisquare IRLS, hard-zero outliers |
| 5 | RANSAC | `coop_loc_ransac.py` | Random consensus, excludes minority |
| 6 | **EKF + χ² + Huber** ★ | `coop_loc_ekf_chi2_huber.py` | χ² innovation gate + Huber update |

All nodes write per-drone CSV logs to `evidence/metrics/` with columns: `t_sec, x, y, z, solve_ms`.

---

## Attacks implemented

| # | Attack | Script | Injection point | STRIDE |
|---|---|---|---|---|
| 1 | Sybil | `sybil_registry_attack.py` | Ranging layer | Spoofing, Tampering |
| 2 | Sybil-consistent | `sybil_consistent_attack.py` | Ranging layer | Spoofing, Tampering |
| 3 | Replay | `replay_attack.py` | Ranging layer | Spoofing, DoS |
| 4 | Replay-gradual | `replay_attack_gradual.py` | Ranging layer | Spoofing, DoS |
| 5 | Wormhole | `wormhole_attack.py` | Ranging layer | Tampering, EoP |
| 6 | Timesync | `timesync_attack.py` | Ranging layer | Spoofing, Tampering |
| 7 | Byzantine insider | `byzantine_insider_attack.py` | Feedback layer | Tampering, EoP |
| 8 | Baseline | — | None (control) | — |

All attack scripts standardise on **px4_2** as the compromised drone. `SMOKE_*` environment variables enable fast 20-second smoke tests.

---

## Quick start — full experiment run

### Step 1 — build the ROS 2 package

```bash
cd ~/Dissertation/ros_ws/px4_ros_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select swarm_msgs swarm_discovery
source install/setup.bash
```

### Step 2 — start the SITL swarm (leave running in background)

```bash
bash ~/Dissertation/scripts/start_swarm.sh
```

This launches 5 PX4 SITL instances, Gazebo Harmonic, and the Micro-XRCE-DDS agent. Wait for the `[+] Swarm ready` message (~35 seconds).

### Step 3 — run a single experiment

```bash
# Usage: run_experiment.sh <approach> <attack>
bash ~/Dissertation/scripts/run_experiment.sh wls baseline
bash ~/Dissertation/scripts/run_experiment.sh ekf_chi2_huber wormhole
bash ~/Dissertation/scripts/run_experiment.sh wls_tukey byzantine
```

Supported approaches: `wls` · `ekf` · `wls_huber` · `wls_tukey` · `ransac` · `ekf_chi2_huber`  
Supported attacks: `baseline` · `sybil` · `sybil_consistent` · `replay` · `replay_gradual` · `wormhole` · `timesync` · `byzantine`

Each run takes ~90 seconds and saves CSVs to `evidence/metrics/`.

### Step 4 — run the full matrix (~6 hours unattended)

```bash
# All 6 approaches × 8 attacks × 5 drones = 240 CSVs
bash ~/Dissertation/scripts/run_all_experiments.sh
```

If any runs were missed (orphaned processes, timeout), re-run only those:

```bash
bash ~/Dissertation/scripts/rerun_missing.sh
```

### Step 5 — analyse and generate figures

```bash
# Main analysis: fig1–fig5 + summary_table.csv
python3 ~/Dissertation/analyse_dissertation.py \
    --gt-csv ~/Dissertation/evidence/gt/gt_px4_1.csv

# Split attack figures (catastrophic vs moderate y-scale)
python3 ~/Dissertation/split_attack_figures.py --drone px4_1

# Add degradation factors to summary table
python3 ~/Dissertation/add_degradation_factor.py

# Validate attack injection actually fired
python3 ~/Dissertation/validate_attacks.py

# Check for FROZEN or SHORT runs
python3 ~/Dissertation/validate_localisation_csvs.py
```

Output figures land in `evidence/figures/dissertation/`.

---

## Live visualisation (RViz2 + Gazebo)

With the SITL swarm running, launch the full ROS 2 stack including `swarm_viz`:

```bash
bash ~/Dissertation/scripts/launch_stack_service.sh
```

Then open RViz2 in a separate terminal:

```bash
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
ros2 run rviz2 rviz2
```

In RViz2:
1. Set **Fixed Frame** to `world`
2. Click **Add → By Topic → /swarm/viz/markers → MarkerArray**

Drone positions (estimated vs ground truth) appear as coloured markers updating at 25 Hz.

### Verify the viz pipeline is live

```bash
ros2 topic info /swarm/viz/markers   # Publisher count should be 1
ros2 topic hz /swarm/viz/markers     # Should show ~25 Hz
```

---

## Running individual scripts

### Launch ROS 2 stack components individually

If you need finer control than the tmux launch scripts provide, source the workspace first and run nodes directly:

```bash
SRC="source /opt/ros/humble/setup.bash && source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash"

# Ground truth
$SRC && python3 ~/Dissertation/code/ground_truth_demux.py

# Ranging
$SRC && python3 ~/Dissertation/code/inter_drone_ranging.py

# Registry (Design A)
$SRC && ros2 run swarm_discovery swarm_registry

# Heartbeats × 5
$SRC && ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 &
$SRC && ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 &
# ... etc for px4_3 px4_4 px4_5

# Localisation (one approach, all 5 drones)
$SRC && ros2 run swarm_discovery coop_loc_dynamic px4_1 &
$SRC && ros2 run swarm_discovery coop_loc_dynamic px4_2 &
# ... etc

# Visualisation
$SRC && ros2 run swarm_discovery swarm_viz
```

### Run an attack manually

```bash
# After the stack is running and baseline is established (~30 s):
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash

# Choose one:
python3 ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/sybil_registry_attack.py
python3 ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/wormhole_attack.py
python3 ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/byzantine_insider_attack.py
# etc.
```

### Smoke test a single attack (~20 seconds)

```bash
SMOKE_DURATION=20 SMOKE_WARMUP=5 \
python3 ~/Dissertation/ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/wormhole_attack.py
```

### Clean up orphaned processes

If a run leaves stale nodes behind (causing the next run's CSV to be corrupted):

```bash
bash ~/Dissertation/scripts/cleanup_swarm.sh

# Verify nothing remains:
bash ~/Dissertation/scripts/cleanup_swarm.sh --check
```

---

## Validation tools

| Script | Purpose | Output |
|---|---|---|
| `validate_attacks.py` | Confirms injected signal actually fired per-attack | PASS / SUSPECT / FAIL / MISSING |
| `validate_localisation_csvs.py` | Detects FROZEN (zero variance) and SHORT (<60 s) runs | List of bad CSVs |
| `add_degradation_factor.py` | Adds `degradation_factor = attack_mean / baseline_mean` to summary | `summary_table_with_degradation.csv` |

Run all three after every full matrix to confirm data quality before analysis.

---

## Key design decisions

**Full relative-vector residuals** (not range-only trilateration) are required for WLS to avoid rank deficiency with collinear anchors — a critical fix achieving sub-centimetre baseline convergence.

**Per-pair independent publishing** in `inter_drone_ranging.py` replaced an all-or-nothing gate that caused cascade dropout when any single drone's ground truth was momentarily stale.

**BEST_EFFORT QoS** is required for all PX4 `/fmu/out` topics — RELIABLE subscribers receive nothing and fail silently.

**gz-transport bypasses ros_gz_bridge** for ground truth extraction because the bridge strips entity names from `Pose_V → TFMessage` conversions. Gazebo model names (`x500_1..x500_5`) are mapped to ROS 2 namespaces (`px4_1..px4_5`) by `extract_ground_truth.py`.

**Spawn position fix** — a critical validity bug: `start_swarm.sh` spawned drones at (0,0), (0,1), (0,2), (0,3), (0,4) but `run_experiment.sh` registered heartbeats at the 5-drone grid (0,0), (2,0), (4,0), (2,2), (4,2). This mismatch introduced systematic anchor bias. Both now use the grid layout.

**Open EKF feedback loop fix** — a second validity bug: publishing `coop/self_estimate` back into the EKF as a cooperative measurement created a closed loop, making EKF results spuriously attack-invariant. The feedback path from the attacker's own node is now gated.

---

## Branches

| Branch | Content |
|---|---|
| `main` | Stable baseline — WLS, 3-drone testbed |
| `attack-experiments` | Sybil, Replay, Wormhole on 3 drones |
| `five-drone-experiments` | 5-drone testbed, WLS + EKF comparison |
| `attack-enhanced-verified` | **Current** — 6 approaches × 8 attacks × 5 drones, full matrix |

---

## Key empirical findings

| Finding | Detail |
|---|---|
| Wormhole is catastrophic for WLS | 88.6 m mean error — 165× degradation |
| Huber soft-weights wormhole partially | 20.2 m — still unbounded |
| Tukey hard-zeros wormhole | 0.54 m — essentially solved |
| Byzantine defeats all robust losses | WLS ≈ WLS+Huber ≈ WLS+Tukey ≈ 38–46 m |
| RANSAC bounds Byzantine | 4.0 m — inlier exclusion quarantines bad anchor |
| EKF+χ²+Huber best baseline accuracy | 0.034 m — 6–16× better than others |
| EKF+χ²+Huber blind spot | Byzantine: 1.0 m (30× degradation) — gradual ramp evades χ² gate |
| Design B impersonation gap | Allowlist blocks unknown IDs but not valid-ID reuse — DDS has no transport-layer auth |

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
