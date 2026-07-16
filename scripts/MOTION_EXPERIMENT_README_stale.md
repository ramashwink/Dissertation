# Motion Experiments — When Drones Go Blind

**Branch:** `motion-experiments`  
**Purpose:** Extends the static hover testbed to moving drones, validating attack effectiveness against dynamic swarms.

---

## How this differs from static experiments

| Aspect | Static (`run_experiment.sh`) | Motion (`run_experiment_motion.sh`) |
|---|---|---|
| Drone position | Fixed at spawn grid | Flying pattern (hover/square/circle) |
| Heartbeats | Fixed spawn coords | Live GT position (`swarm_heartbeat_dynamic`) |
| QGC | Not needed | Monitor via ports 18571–18575 |
| Warmup | 12s | 25s (arm + climb to altitude) |
| CSV location | `evidence/metrics/` | `evidence/metrics/motion/` |
| CSV naming | `{approach}_px4_N_{attack}.csv` | `{approach}_px4_N_{attack}_{pattern}.csv` |

---

## Prerequisites

```bash
# Terminal 1 — SITL swarm (leave running)
bash ~/Dissertation/scripts/start_swarm.sh

# Terminal 2 — QGC (optional, for monitoring)
# Connect to UDP 18571, 18572, 18573, 18574, 18575
# Watch drones arm and fly when formation_flight starts

# Terminal 3 — RViz (leave open)
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_wx/install/setup.bash
ros2 run rviz2 rviz2 -d ~/Dissertation/rviz/swarm_demo.rviz
```

Make sure all nodes are built:

```bash
cd ~/Dissertation/ros_ws/px4_ros_wx
source /opt/ros/humble/setup.bash
colcon build --packages-select swarm_msgs swarm_discovery
source install/setup.bash

# Verify new nodes exist:
ros2 pkg executables swarm_discovery | grep -E "heartbeat_dynamic|formation"
```

---

## Running motion experiments

### Single experiment

```bash
# Usage: bash run_experiment_motion.sh <approach> <attack> [pattern]
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber baseline hover
bash ~/Dissertation/scripts/run_experiment_motion.sh wls wormhole square
bash ~/Dissertation/scripts/run_experiment_motion.sh ransac byzantine circle
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber targeted_ramp hover
```

### Full motion matrix (hover only — recommended for dissertation)

```bash
for approach in wls ekf wls_huber wls_tukey ransac ekf_chi2_huber; do
  for attack in baseline wormhole byzantine sybil replay targeted_ramp; do
    bash ~/Dissertation/scripts/run_experiment_motion.sh $approach $attack hover
    sleep 10
  done
done
```

### Compare static vs motion for key attacks

```bash
# Static (existing data already collected):
ls ~/Dissertation/evidence/metrics/ekf_chi2_huber_px4_1_targeted_ramp.csv

# Motion (new):
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber targeted_ramp hover
ls ~/Dissertation/evidence/metrics/motion/ekf_chi2_huber_px4_1_targeted_ramp_hover.csv
```

---

## Interactive demo (viva)

```bash
# Baseline — drones hover, yellow balls track them
bash ~/Dissertation/scripts/demo_motion.sh ekf_chi2_huber

# Wormhole on moving WLS — watch balls diverge while drones fly
bash ~/Dissertation/scripts/demo_motion.sh wls wormhole square

# Targeted F4 attack on moving EKF+chi2+Huber
bash ~/Dissertation/scripts/demo_motion.sh ekf_chi2_huber targeted_ramp hover

# Byzantine while drones fly circle
bash ~/Dissertation/scripts/demo_motion.sh ransac byzantine circle
```

Each demo: stack launches → drones arm and fly → press Enter to inject → press Enter to stop → drones land automatically.

---

## QGC port mapping

| Drone | MAVLink UDP port |
|---|---|
| px4_1 | 18571 |
| px4_2 | 18572 |
| px4_3 | 18573 |
| px4_4 | 18574 |
| px4_5 | 18575 |

Connect QGC to `localhost:18571` to monitor px4_1. You can open multiple QGC instances or use the multi-vehicle view.

---

## Flight patterns

### hover
Arms all drones, takes off to 5m, holds position. Useful for baseline motion experiment (small dynamics from wind/vibration, no translation).

### square
Each drone flies an 8m × 8m square at 5m altitude, offset by their spawn position so formation spacing is maintained. Period ≈ 21 seconds.

### circle
Each drone flies a 4m radius circle at 5m altitude around its spawn position. Full rotation ≈ 17 seconds.

---

## New files in this branch

```
ros_ws/px4_ros_wx/src/swarm_discovery/swarm_discovery/
├── swarm_heartbeat_dynamic.py    ← broadcasts live GT position (not fixed spawn)
└── formation_flight.py           ← offboard control: hover/square/circle

scripts/
├── run_experiment_motion.sh      ← motion variant of run_experiment.sh
├── demo_motion.sh                ← interactive motion demo
└── MOTION_EXPERIMENT_README.md   ← this file

evidence/
├── metrics/motion/               ← motion experiment CSVs
└── gt/motion/                    ← motion ground truth CSVs
```

---

## What to expect in results

Under **hover**: slightly higher baseline error than static (0.05–0.10 m vs 0.034 m for EKF+χ²+Huber) because the constant-velocity model has velocity uncertainty even at hover.

Under **square/circle**: higher baseline error (0.10–0.20 m) because drones accelerate through corners and the EKF covariance inflates. Attack impact should be proportionally similar to static.

Key dissertation insight for motion: the **targeted F4 attack** (`targeted_ramp`) becomes *more* effective under motion because EKF covariance inflation increases `S_per_axis`, raising the maximum undetectable bias ceiling above 0.307 m. The same mathematical derivation with `S_per_axis = 0.08–0.12 m²` (vs 0.05 at static) gives:

```
max_bias_motion = √(7.815 × 0.10 / 3) × 0.85 = 0.435 m
```

Still below Huber delta (0.5 m) — still bypasses both defences — but with a larger margin for corruption.

---

## Troubleshooting

**Drones don't arm:**
```bash
# Check PX4 pre-arm state via QGC — common issues:
# - EKF not initialised (wait longer after start_swarm.sh)
# - Arming check failures in pxh> terminal
# Run start_swarm.sh and wait 60s before running motion experiments
```

**formation_flight exits immediately:**
```bash
# Check px4_msgs are available:
ros2 interface list | grep px4_msgs
# If empty: source /opt/ros/humble/setup.bash && source ~/Dissertation/ros_ws/px4_ros_wx/install/setup.bash
```

**Dynamic heartbeats not updating:**
```bash
# Check ground_truth_demux is publishing:
ros2 topic hz /sim/ground_truth/px4_1/pose
# Should show ~25 Hz. If not, gz-transport isn't running — check Gazebo is up.
```

**Drones don't land at end:**
```bash
# Land manually via QGC or:
for i in 1 2 3 4 5; do
  ros2 topic pub --once /px4_${i}/fmu/in/vehicle_command \
    px4_msgs/msg/VehicleCommand \
    "{command: 21, param1: 0.0, target_system: $((i+1)), target_component: 1}"
done
```

---

*MSc Dissertation — COMSM0117 — University of Bristol — 2026*  
*Branch: `motion-experiments`*
