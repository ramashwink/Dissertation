# Motion Experiments

**Branch:** `motion-experiments`  
**Purpose:** Extends the static hover testbed to flying drones, validating attack
effectiveness against dynamic swarms and enabling static vs. motion comparison.

---

## Static vs. motion comparison

| Aspect | Static (`run_experiment.sh`) | Motion (`run_experiment_motion.sh`) |
|---|---|---|
| Drone state | Landed at spawn grid | Flying pattern (hover / square / circle) |
| Heartbeat positions | Fixed spawn coordinates | Live Gazebo ground truth (`swarm_heartbeat_dynamic`) |
| Warmup | 12 s | 25 s (arm + climb + stabilise) |
| Altitude wait | — | 30 s |
| CSV location | `evidence/metrics/` | `evidence/metrics/motion/` |
| CSV naming | `{approach}_px4_N_{attack}.csv` | `{approach}_px4_N_{attack}_{pattern}.csv` |
| QGC monitoring | Not needed | Ports 18571–18575 |

---

## Quick start

```bash
# Terminal 1 — start swarm (leave running)
bash ~/Dissertation/scripts/start_swarm_motion.sh

# Terminal 2 — single experiment
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber baseline hover

# Terminal 2 — full batch (hover, all 6 approaches × 11 attacks)
bash ~/Dissertation/scripts/run_all_experiments_motion.sh

# Terminal 2 — all three patterns
bash ~/Dissertation/scripts/run_all_experiments_motion.sh all
```

---

## Prerequisites

### 1. Build the workspace

```bash
cd ~/Dissertation/ros_ws/px4_ros_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select swarm_msgs swarm_discovery
source install/setup.bash
```

Verify the motion nodes were built:

```bash
ros2 pkg executables swarm_discovery | grep -E "heartbeat_dynamic|formation_flight"
# Expected:
#   swarm_discovery formation_flight
#   swarm_discovery swarm_heartbeat_dynamic
```

### 2. Start the swarm

```bash
bash ~/Dissertation/scripts/start_swarm_motion.sh
```

Wait for the `SWARM READY` banner (~55 s). The swarm stays running between experiments — you do not need to restart it for each run.

---

## Running experiments

### Single experiment

```bash
bash ~/Dissertation/scripts/run_experiment_motion.sh <approach> <attack> [pattern]
```

| Parameter | Values |
|---|---|
| `approach` | `wls` · `ekf` · `wls_huber` · `wls_tukey` · `ransac` · `ekf_chi2_huber` |
| `attack` | `baseline` · `sybil` · `replay` · `wormhole` · `sybil_consistent` · `replay_gradual` · `byzantine` · `timesync` · `targeted_ramp` · `targeted_osc` · `targeted_two_drone` |
| `pattern` | `hover` (default) · `square` · `circle` |

Examples:

```bash
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber baseline hover
bash ~/Dissertation/scripts/run_experiment_motion.sh wls wormhole square
bash ~/Dissertation/scripts/run_experiment_motion.sh ransac byzantine circle
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber targeted_ramp hover
```

### Full batch — hover (recommended for dissertation)

Runs 6 approaches × 11 attacks = **66 experiments** (~3.5 hours).  
Already-completed runs are skipped automatically on re-run.

```bash
bash ~/Dissertation/scripts/run_all_experiments_motion.sh
# or explicitly:
bash ~/Dissertation/scripts/run_all_experiments_motion.sh hover
```

### Full batch — all patterns

Runs 6 × 11 × 3 = **198 experiments** (~10 hours).

```bash
bash ~/Dissertation/scripts/run_all_experiments_motion.sh all
```

### Output

```
evidence/metrics/motion/
  {approach}_px4_N_baseline_{pattern}.csv
  {approach}_px4_N_{attack}_{pattern}.csv

evidence/gt/motion/
  gt_px4_N_{approach}_{attack}_{pattern}.csv
```

---

## RViz visualisation

### What is shown

`swarm_viz` publishes a single `MarkerArray` on `/swarm/viz/markers`.
RViz2 renders it using `swarm_viz.rviz`.

| Marker | Colour | Meaning |
|---|---|---|
| `ground_truth` spheres | Green | Actual drone positions from Gazebo |
| `wls_estimate` spheres | Yellow | Cooperative localisation estimates |
| `error_vec` lines | Red | Vector from estimate to ground truth (error magnitude) |
| `ghost_drones` spheres | Pink | Sybil ghost drones injected by attack |
| `topology` lines | Blue | Inter-drone ranging links |

### Starting RViz during an experiment

Open a separate terminal **after** an experiment is running (step 3/7 or later):

```bash
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
ros2 run rviz2 rviz2 -d ~/Dissertation/swarm_viz.rviz
```

### Verifying all visuals are publishing

Run these checks while an experiment is active:

```bash
# 1. Confirm swarm_viz is running
pgrep -af swarm_viz

# 2. Confirm the marker topic is publishing (~10 Hz)
ros2 topic hz /swarm/viz/markers

# 3. Confirm publisher is attached
ros2 topic info /swarm/viz/markers
# Expected: Publisher count: 1

# 4. Check the ground truth feed (required for green spheres)
ros2 topic hz /sim/ground_truth/px4_1/pose
# Expected: ~25 Hz

# 5. Check the localisation estimate feed (required for yellow spheres)
ros2 topic hz /px4_1/coop/self_estimate
# Expected: ~10 Hz

# 6. Check the registry (required for ghost detection)
ros2 topic echo /swarm/registry --once | grep total_seen
# Expected: total_seen: 5
```

All six checks passing means every visual layer is live in RViz.

### Namespace not appearing in RViz?

If a namespace shows no markers after the experiment starts:

| Missing namespace | Root cause | Fix |
|---|---|---|
| `ground_truth` | `ground_truth_demux` not running | Check tmux window `gt` in the experiment session |
| `wls_estimate` | Localisation algorithm not started | Check tmux window `algorithm` |
| `ghost_drones` | No attack running or attack is not Sybil | Expected for non-Sybil attacks |
| `error_vec` | Both of the above (needs GT + estimate) | Fix GT and estimate feeds first |
| `topology` | Ranging node not running | Check tmux window `ranging` |

---

## Flight patterns

### `hover`
Arms all drones, climbs to 5 m, holds position. Minimal lateral dynamics — most comparable to the static scenario.

### `square`
Each drone flies an 8 m × 8 m square at 5 m altitude offset by its spawn position (formation spacing is maintained). Period ≈ 21 s.

### `circle`
Each drone flies a 4 m radius circle at 5 m altitude around its spawn position. Full rotation ≈ 17 s.

---

## QGC port mapping

| Drone | MAVLink UDP port |
|---|---|
| px4_1 | 18571 |
| px4_2 | 18572 |
| px4_3 | 18573 |
| px4_4 | 18574 |
| px4_5 | 18575 |

---

## File map

```
scripts/
├── start_swarm_motion.sh          start Gazebo + 5 PX4 SITL drones
├── run_experiment_motion.sh       run one approach/attack/pattern combination
├── run_all_experiments_motion.sh  run the full batch with resume support
├── smoke_test_motion.sh           30 s end-to-end sanity check
└── demo_motion.sh                 interactive viva demo

ros_ws/px4_ros_ws/src/swarm_discovery/swarm_discovery/
├── swarm_heartbeat_dynamic.py     broadcasts live GT position (not fixed spawn)
├── formation_flight.py            offboard control: hover / square / circle
└── swarm_viz.py                   publishes /swarm/viz/markers for RViz2

evidence/
├── metrics/motion/                motion experiment CSVs
└── gt/motion/                     motion ground truth CSVs

swarm_viz.rviz                     RViz2 config (MarkerArray on /swarm/viz/markers)
```

---

## Troubleshooting

**Drones do not arm:**
```bash
# Check EKF is initialised — wait 60 s after start_swarm_motion.sh before running.
# Check RC failsafe params were applied:
tail -5 /tmp/px4_1.log | grep -i "arm\|fail"
```

**`formation_flight` exits immediately:**
```bash
# px4_msgs must be sourced:
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
ros2 interface list | grep px4_msgs | head -3
```

**Dynamic heartbeats not updating (yellow spheres frozen):**
```bash
# Ground truth demux must be running:
ros2 topic hz /sim/ground_truth/px4_1/pose
# Should be ~25 Hz. If zero, Gazebo bridge is down — restart start_swarm_motion.sh.
```

**Drones do not land at end of experiment:**
```bash
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
for i in 1 2 3 4 5; do
  ros2 topic pub --once /px4_${i}/fmu/in/vehicle_command \
    px4_msgs/msg/VehicleCommand \
    "{command: 21, param1: 0.0, target_system: $((i+1)), target_component: 1}"
done
```

**Batch runner aborts mid-way (swarm died):**
```bash
# Restart the swarm, then re-run the batch — completed CSVs are skipped:
bash ~/Dissertation/scripts/start_swarm_motion.sh
bash ~/Dissertation/scripts/run_all_experiments_motion.sh
```

---

*MSc Dissertation — COMSM0117 — University of Bristol — 2026*
