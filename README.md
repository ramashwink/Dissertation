# When Drones Go Blind
### Security Analysis of Cooperative LiDAR-Based Localisation for Indoor GPS-Denied Drone Swarms

> *A single rogue insider drone can corrupt every other drone's view of where it is — and there is currently no standard defence.*

**MSc Cyber Security & Infrastructure Security · COMSM0117**  
University of Bristol · Dissertation 2025–2026  
Supervisor: Dr Joe Gardiner · Co-supervisor: Dr Alma Oracevic  

---

## Overview

This repository contains the full research testbed for an MSc dissertation investigating **insider threat attacks on cooperative LiDAR-based localisation** in GPS-denied drone swarms.

The core threat model: an *evil drone* — a legitimate swarm member that has been compromised — can manipulate its reported position, inject ghost drones, replay stale measurements, or tunnel false data across the swarm via wormhole attacks. The swarm trusts it implicitly.

**Research Questions**
1. What are the primary security vulnerabilities in cooperative LiDAR-based localisation algorithms in GPS-denied swarm environments?
2. What are the trade-offs between security, positioning accuracy, communication efficiency, and computational cost when mitigating those vulnerabilities?

---

## Repository Structure

```
.
├── code/
│   ├── cooperative_localisation.py   # WLS cooperative localisation node (Step 3)
│   ├── ground_truth_demux.py         # gz-transport ground truth publisher (Step 1)
│   ├── inter_drone_ranging.py        # LiDAR noise model + range publisher (Step 2)
│   ├── px4_offboard_hover.py         # Offboard hover controller
│   ├── px4_position_listener.py      # EKF2 position subscriber
│   ├── px4_spoof_position.py         # EKF2-layer position spoof (insider attack)
│   ├── sybil_ghost_attack.py         # Sybil / ghost drone injection
│   ├── replay_attack.py              # Replay attack on range measurements
│   ├── capture_sybil.py              # pcap capture of Sybil traffic
│   ├── record_baseline.py            # Nominal swarm baseline recorder
│   ├── attack_test.py                # Attack harness / runner
│   └── analyse_attack.py             # Post-hoc log analysis
├── evidence/
│   └── attack_evidence.png           # Visual evidence of attack outcomes
├── logs/
│   ├── attack2_results.txt           # Attack experiment results
│   ├── attack_logs/                  # Per-run logs
│   └── sybil_evidence.pcap           # Wireshark capture of Sybil traffic
├── scripts/
│   └── start_lab.sh                  # Full swarm bring-up script
├── ros_ws/
│   └── px4_ros_ws/                   # ROS 2 workspace (px4_msgs, custom nodes)
└── tools/
    ├── PX4-Autopilot/                # PX4 SITL (built from source)
    ├── Micro-XRCE-DDS-Agent/         # DDS bridge (built from source)
    └── ardupilot/                    # ArduPilot reference
```

---

## Testbed Stack

| Layer | Technology |
|---|---|
| Flight controller | PX4 SITL (`gz_x500`, autostart 4001) |
| Simulator | Gazebo Harmonic |
| Middleware | ROS 2 Humble + Micro XRCE-DDS Agent |
| Ground truth | `gz-transport` Python bindings (bypasses `ros_gz_bridge`) |
| Cooperative localisation | WLS trilateration via `scipy.optimize.least_squares` |
| GCS | QGroundControl (Windows host → WSL2 via UDP) |
| Platform | Ubuntu 22.04 LTS in WSL2 on Windows 11 |

**Swarm configuration:** 3 drones, namespaces `px4_1/px4_2/px4_3`, MAVLink system IDs 2/3/4, spawned at `(0,0,0)`, `(0,1,0)`, `(0,2,0)`.

---

## Cooperative Localisation Stack

Built in three steps, each validated before proceeding:

**Step 1 — Ground truth** (`ground_truth_demux.py`)  
Publishes per-drone poses at 50 Hz on `/sim/ground_truth/px4_N/pose` via `gz-transport` Python bindings. Uses direct gz-transport to avoid the silent entity-name stripping bug in `ros_gz_bridge`.

**Step 2 — Inter-drone ranging** (`inter_drone_ranging.py`)  
Simulates LiDAR-derived relative position vectors with noise (σ_range = 0.05 m, σ_bearing = 0.0087 rad), publishing at 25 Hz on `/px4_N/coop/range_to/px4_M`.

**Step 3 — Cooperative localisation** (`cooperative_localisation.py`)  
WLS solver using full 3D relative-vector residuals (6 residuals vs 3 unknowns), resolving the rank deficiency of range-only trilateration with collinear anchors. Warm-started from previous estimate (soft temporal prior). Based on Patwari et al., IEEE SPM 2005.

---

## Attack Experiments

### EKF2 Position Spoof (demonstrated)
Injecting false `vehicle_visual_odometry` messages causes the target drone to accelerate to **64 m/s** — worst-case single-source position fusion failure under an insider attack.

### Sybil / Ghost Drone Injection (`sybil_ghost_attack.py`)
Evil drone publishes fabricated neighbour positions on the cooperative localisation topics, corrupting the WLS estimates of honest drones.

### Replay Attack (`replay_attack.py`)
Captures and re-injects stale range measurements, causing honest drones to localise against an outdated swarm configuration.

---

## Key Technical Notes

- All PX4 `/fmu/out` subscriptions **silently fail** without `BEST_EFFORT` QoS — set this explicitly or you receive nothing.
- `ros_gz_bridge` silently strips entity names from `Pose_V → TFMessage` conversions — use `gz-transport` Python bindings directly.
- Range-only trilateration is rank-deficient for collinear anchor configurations — use full relative-vector residuals (position vectors, not scalars).

---

## Threat Model (STRIDE mapping)

| Attack | STRIDE categories |
|---|---|
| Sybil / ghost drone injection | Spoofing, Tampering |
| Wormhole | Tampering, Elevation of privilege |
| Replay | Spoofing, Denial of service |
| EKF2 position spoof | Spoofing, Tampering |

---

## Running the Testbed

```bash
# 1. Bring up the full stack
bash scripts/start_lab.sh

# 2. Ground truth (separate terminal)
python3 code/ground_truth_demux.py

# 3. Inter-drone ranging (separate terminal)
python3 code/inter_drone_ranging.py

# 4. Cooperative localisation — one per drone
python3 code/cooperative_localisation.py px4_1
python3 code/cooperative_localisation.py px4_2
python3 code/cooperative_localisation.py px4_3

# 5. Run an attack
python3 code/sybil_ghost_attack.py px4_2   # px4_2 is the evil drone
```

---

## References

- Patwari et al., *Locating the Nodes*, IEEE Signal Processing Magazine, 2005
- Newsome et al., *The Sybil Attack in Sensor Networks*, IPSN 2004
- Hu, Perrig & Johnson, *Wormhole Attacks in Wireless Networks*, IEEE JSAC 2006
- Swarm-LIO2, IEEE Transactions on Robotics, 2024
- UK CAA CAP 3040 — BVLOS regulatory framework

---

## Status

| Milestone | Status |
|---|---|
| Literature review (20+ papers) | ✅ Complete |
| Threat model (STRIDE) | ✅ Complete |
| Testbed build (PX4 SITL + ROS 2) | ✅ Complete |
| Cooperative localisation stack | ✅ Complete |
| EKF2 spoof attack | ✅ Demonstrated |
| Sybil / Replay / Wormhole attacks | 🔄 In progress |
| Mitigation design | ⬜ Upcoming |
| Dissertation submission | ⬜ 4 September 2026 |

---

*MSc Cyber Security & Infrastructure Security · University of Bristol · 2026*
