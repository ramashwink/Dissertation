# Swarm Localisation Demo — Quick Reference

## Prerequisites

Three things must already be running before any demo command:

```bash
# Terminal 1 — SITL swarm (leave running the whole session)
bash ~/Dissertation/scripts/start_swarm.sh

# Terminal 2 — RViz (leave open, never touch)
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
ros2 run rviz2 rviz2 -d ~/Dissertation/rviz/swarm_demo.rviz

# Terminal 3 — run demo commands here
```

In RViz: **teal spheres = ground truth**, **yellow spheres = estimated position**, **blue lines = ranging topology**

---

## Usage

```bash
bash ~/Dissertation/scripts/demo.sh <approach> [attack]
```

- If no attack given: baseline only, press Enter to stop
- If attack given: baseline first → Enter to inject → Enter to stop → Enter to end
- RViz stays live between every run

---

## All Approaches

| Argument | Algorithm | What it does |
|---|---|---|
| `wls` | Weighted Least Squares | Baseline, no outlier rejection |
| `ekf` | Extended Kalman Filter | Dynamics model, no outlier rejection |
| `wls_huber` | WLS + Huber loss | Soft down-weights outlier ranges |
| `wls_tukey` | WLS + Tukey bisquare | Hard-zeros outlier ranges |
| `ransac` | RANSAC | Inlier consensus, excludes minority |
| `ekf_chi2_huber` | EKF + χ² gate + Huber | Best accuracy, chi-squared innovation gate |

---

## All Attacks

| Argument | Attack | Layer | What you see in RViz |
|---|---|---|---|
| `wormhole` | Wormhole | Ranging | Balls fly far off (up to 88m error on WLS) |
| `byzantine` | Byzantine insider | Feedback | Slow drift, bypasses range-residual defences |
| `sybil` | Sybil | Registry + Ranging | Ghost anchors pull estimates off |
| `sybil_consistent` | Sybil consistent | Ranging | Subtler ghost — plausible fake positions |
| `replay` | Replay (5s delay) | Ranging | Stale measurements, bounded drift |
| `replay_gradual` | Replay gradual | Ranging | Slow accumulating drift |
| `timesync` | Timesync | Ranging | Clock skew bias, similar to replay |

---

## Recommended Demo Sequences

### Sequence A — Full story (15 min, best for viva)

```bash
# 1. Show clean baseline
bash ~/Dissertation/scripts/demo.sh wls

# 2. Wormhole destroys WLS — balls fly off
bash ~/Dissertation/scripts/demo.sh wls wormhole

# 3. Tukey defeats wormhole — balls hold tight
bash ~/Dissertation/scripts/demo.sh wls_tukey wormhole

# 4. Byzantine bypasses Tukey — different attack surface
bash ~/Dissertation/scripts/demo.sh wls_tukey byzantine

# 5. RANSAC contains Byzantine
bash ~/Dissertation/scripts/demo.sh ransac byzantine
```

### Sequence B — Algorithm comparison (10 min)

```bash
# Same attack, three algorithms — shows the trade-off
bash ~/Dissertation/scripts/demo.sh wls wormhole
bash ~/Dissertation/scripts/demo.sh wls_huber wormhole
bash ~/Dissertation/scripts/demo.sh wls_tukey wormhole
```

### Sequence C — Byzantine escalation (10 min)

```bash
# Show Byzantine defeating each range-residual defence
bash ~/Dissertation/scripts/demo.sh wls byzantine
bash ~/Dissertation/scripts/demo.sh wls_huber byzantine
bash ~/Dissertation/scripts/demo.sh wls_tukey byzantine
bash ~/Dissertation/scripts/demo.sh ransac byzantine
```

### Sequence D — Best algorithm showcase (5 min)

```bash
# Show EKF+chi2+Huber accuracy at baseline vs under attack
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber wormhole
bash ~/Dissertation/scripts/demo.sh ekf_chi2_huber byzantine
```

### Sequence E — Replay and timing attacks (5 min)

```bash
bash ~/Dissertation/scripts/demo.sh wls replay
bash ~/Dissertation/scripts/demo.sh wls replay_gradual
bash ~/Dissertation/scripts/demo.sh wls timesync
```

---

## Troubleshooting

**Yellow balls not appearing after stack launches:**
```bash
# Check registry has all 5 drones:
ros2 topic echo /swarm/registry --once | grep total_seen
# Should say: total_seen: 5

# Check localisation nodes are running:
ros2 node list | grep cooperative
# Should show 5 nodes
```

**RViz goes blank:**
```bash
# swarm_viz died — restart it:
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
ros2 run swarm_discovery swarm_viz &
```

**Demo hangs at registry wait:**
```bash
# In a second terminal, restart heartbeats manually:
source /opt/ros/humble/setup.bash
source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 &
ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 &
ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 &
ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 &
ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 &
```

**Nuclear reset (if everything breaks):**
```bash
bash ~/Dissertation/scripts/cleanup_swarm.sh
bash ~/Dissertation/scripts/start_swarm.sh
# Then rerun demo command
```

---

## What to say during the demo

**On baseline:** "All five drones are running cooperative localisation with no attack. Yellow estimated positions sit on top of teal ground truth — sub-centimetre error."

**On wormhole injecting:** "I'm now injecting a wormhole attack through px4_2. It compresses range measurements to 5% of true value, corrupting the geometry of the entire neighbourhood."

**On Tukey recovering:** "The same attack on WLS+Tukey — the bisquare loss hard-zeros the corrupted range constraints entirely, so the solution is unaffected."

**On Byzantine:** "Byzantine is different — it poisons the feedback layer, not the ranging layer. Huber and Tukey have no visibility there, which is why all three look the same."

**On RANSAC:** "RANSAC's inlier consensus quarantines the attacker's estimate when it's inconsistent with the majority — bounding Byzantine error to around 4 metres."
