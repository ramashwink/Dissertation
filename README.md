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

## Motion experiment pipeline

A separate testbed variant where drones fly a coordinated pattern (hover / square / circle) instead of holding a fixed spawn position, so localisation and attacks are evaluated against moving targets. Same 6 approaches, same attack set, plus 3 targeted-attack variants aimed at a specific drone. Uses its own scripts — `start_swarm_motion.sh` / `run_experiment_motion.sh` — not the static-testbed scripts above.

### Quick start

```bash
# 1. Start the swarm (same build step as the static testbed first)
bash ~/Dissertation/scripts/start_swarm_motion.sh
# Wait for "[+] SWARM READY"

# 2. Run one combo — usage: run_experiment_motion.sh <approach> <attack> [pattern]
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf baseline hover
bash ~/Dissertation/scripts/run_experiment_motion.sh ekf_chi2_huber targeted_two_drone circle

# Patterns: hover | square | circle  (default hover)
# Extra attacks beyond the static set: targeted_ramp | targeted_osc | targeted_two_drone
```

CSVs land in `evidence/metrics/motion/`, tagged `{approach}_px4_N_{attack}_{pattern}.csv`. Each run takes ~2 minutes (60s OFFBOARD wait + 25s stabilise + 90s collection).

### Infrastructure fixes (2026-07-13)

A multi-hour debugging session traced the historical "some drones log little/no data" bug to its actual root cause and fixed it at the infrastructure level. In order of what a fresh run now goes through:

1. **Fast-DDS Discovery Server replaces multicast discovery** (`start_swarm_motion.sh`, `run_experiment_motion.sh`). WSL2's virtual network adapter doesn't support IPv4 UDP multicast (confirmed via `ip maddr show lo` — zero IPv4 groups joined, only IPv6), which is what Fast-DDS's default SPDP discovery depends on. A publisher and a subscriber that don't happen to start within a narrow lucky window during swarm boot would silently never discover each other — this was the actual cause of the registry staying empty, heartbeats stuck at "waiting for ground truth", and every downstream node (ranging, EKF, logger) producing zero rows. `start_swarm_motion.sh` exports `ROS_DISCOVERY_SERVER=127.0.0.1:11811` for every `rclpy`/ROS2-native node (via `$SRC`, or explicitly where a `ros2` command runs directly in the script body) instead of the old `FASTRTPS_DEFAULT_PROFILES_FILE` unicast-profile workaround (`config/fastdds_unicast.xml`, now superseded — its `initialPeersList` never specified a port, so it could only ever reach one lucky participant slot).
2. **Discovery server must be version-matched to the Agent, not ROS2 Humble's bundled one** (`start_swarm_motion.sh`) — found and fixed 2026-07-13 post-restart, after item 1 above stopped working following a PC restart. ROS2 Humble bundles Fast-DDS **2.6.11** (`/opt/ros/humble/lib/libfastrtps.so.2.6`); `MicroXRCEAgent` is built against a separately-fetched Fast-DDS **3.6.1** (`/usr/local/lib/libfastdds.so.3.6.1.0`, source at `tools/Micro-XRCE-DDS-Agent/build/fastdds/src/fastdds`). The Agent's internal DDS participants (one per bridged PX4 topic) never registered with a Discovery Server hosted by the 2.6.x binary — confirmed via `ss -uapn` showing the Agent had fallen back to default multicast SPDP ports (7410-7421) despite `ROS_DISCOVERY_SERVER` being set in its environment, and `ros2 topic list` seeing zero `px4_N/...` topics even with a correct `SUPER_CLIENT` XML profile loaded via `FASTDDS_DEFAULT_PROFILES_FILE` (the Fast-DDS-3.x-renamed env var — 2.x used `FASTRTPS_DEFAULT_PROFILES_FILE`). Fix: build this project's own version-matched discovery server from the already-fetched 3.6.1 source tree (`cmake -DCOMPILE_TOOLS=ON .` then `make fast-discovery-server` in `tools/Micro-XRCE-DDS-Agent/build/fastdds/src/fastdds-build`, binary lands at `tools/fds/fast-discovery-server-1.0.1`) and run it in direct SERVER mode: `fast-discovery-server-1.0.1 42 -i 0 -l 127.0.0.1 -p 11811` (command index `42` = `ToolCommand::SERVER`; this raw build's CLI takes a numeric mode index as `argv[1]` since it lacks the ROS2-side python dispatcher — `fastdds discovery` — that normally supplies it; indices `0`/`1` are `AUTO`/`START`, a daemon-manager mode that computes its own port from domain ID and ignores `-p`). `start_swarm_motion.sh` also now sets `FASTDDS_DEFAULT_PROFILES_FILE=config/fastdds_agent_superclient.xml` (a `SUPER_CLIENT` profile pointing at this server's GUID prefix) specifically before launching `MicroXRCEAgent`. Confirmed fixed: all `px4_1`-`px4_5` `/fmu/in|out/...` topics visible in `ros2 topic list` immediately after a fresh swarm boot.
3. **`/dev/shm/fastrtps_*` purged on every swarm boot** (`start_swarm_motion.sh`). Fast-DDS's shared-memory transport and port-lock files only get cleaned up on a graceful shutdown; repeated `kill -9`s across a long session leak them (confirmed 318 stale files after one evening of testing), degrading discovery for new participants over time.
4. **px4_5 (last-spawned drone) gets its own settle-time sleep** (`start_swarm_motion.sh`), matching what px4_2/3/4 already had, instead of relying solely on the blanket post-spawn wait.
5. **`formation_flight` auto-restarts once on an OFFBOARD timeout** (`run_experiment_motion.sh`, step `[4/7]`). If not all 5 drones confirm ARMED+OFFBOARD within `ALTITUDE_WAIT` seconds, the script kills and relaunches the `formation_flight` node fresh and waits again, instead of just logging a warning and proceeding on stale connections.
6. **The 5-way `coop_loc_ekf`/algorithm and `coop_loc_logger` launches are staggered** (`run_experiment_motion.sh`, step `[5/7]`) with a small delay between each, mirroring the heartbeat loop's existing pattern — reduces how many DDS participants join in one tight burst.
7. **`run_all_experiments_motion.sh`'s `swarm_alive()` liveness gate was silently always failing** — it never exported `ROS_DISCOVERY_SERVER` before its own `ros2 topic list` check (unlike every other `ros2`-invoking spot in the pipeline), and separately had a `grep -c ... || echo 0` pattern that double-prints on a zero-match (`grep -c` already prints `0` and exits 1, so the `||` appended a second `0`, producing the literal string `"0\n0"` and breaking the `[ -ge 5 ]` integer test with `integer expression expected`). Fixed by exporting the env var and dropping the redundant `|| echo 0`.

### Debugging guide

Check these **in order** — most upstream cause first, since a failure early in the pipeline produces symptoms that look identical further downstream (an empty registry and a dead Gazebo process both end up as "zero rows in every CSV").

| Symptom | Check | Likely cause / fix |
|---|---|---|
| Everything seems stuck, no drone movement in QGC | `ps aux \| grep "gz sim"` | Gazebo's physics engine can crash silently (SIGABRT deep in `libdart`/`libode` during collision detection — pre-existing, known-flaky, not caused by anything above). Check `/tmp/px4_1.log` for a crash stack trace (px4_1 owns/launches Gazebo headless, so its log captures Gazebo's stdout). If dead, there's no recovery except rebooting the whole swarm (`start_swarm_motion.sh` again). |
| Registry stuck at `Live: []` / heartbeats stuck at "waiting for ground truth" / `ros2 topic list` shows no `px4_N/...` topics | `ps aux \| grep fast-discovery-server` — confirm it's running the **project's own** `tools/fds/fast-discovery-server-1.0.1` binary, not `/opt/ros/humble/bin/fast-discovery-server` | Most likely cause (found 2026-07-13): the discovery server is version-mismatched against the Agent (ROS2 Humble's bundled Fast-DDS 2.6.x vs the Agent's 3.6.1) — the Agent's participants silently fall back to broken multicast. Check `ss -uapn \| grep $(pgrep -f MicroXRCEAgent)` for ports in the 7410-7421 range (the multicast-fallback tell). Fix is already wired into `start_swarm_motion.sh` (see infra fix #2 above) — if it recurs, confirm that script wasn't reverted/edited to point back at the plain `fastdds discovery` command. If the version-matched server *is* running and this still happens, first confirm Gazebo is alive (previous row), then confirm `ROS_DISCOVERY_SERVER` propagated to every `ros2`-invoking code path (`grep -rn ROS_DISCOVERY_SERVER scripts/`). |
| `Registry total_seen=` prints blank in the run log | — | Cosmetic only, not a real health signal — ignore it. The script parses this via `ros2 topic echo \| grep total_seen`, and `ros2 topic echo` is unreliable for this workspace-custom message type (`swarm_msgs/msg/SwarmRegistry`) regardless of whether the registry is actually healthy. Trust the registry's own log (`tmux capture-pane ...:registry`) instead. |
| `WARNING: drones not all OFFBOARD after 60s` | `tmux capture-pane -t <session>:flight -p \| tail -30` | Shows exactly which drone(s) are stuck and their `armed`/`offboard` state. If a specific drone never even attempts to arm (no `Preflight Fail`/`Arming denied` in `/tmp/px4_N.log`), suspect a DDS discovery gap (see above). If it does attempt but PX4 rejects it, see the next row. |
| `/tmp/px4_N.log` shows `WARN [commander] Arming denied: Resolve system health failures first` | A direct rclpy probe subscribing to `VehicleCommandAck` on that drone's `vehicle_command_ack` topic — `result=1` means `MAV_RESULT_TEMPORARILY_REJECTED` | A genuine, legitimate PX4 health-check rejection (commonly EKF/sensor convergence lag), not a ROS2/DDS issue. Usually resource-contention-driven — check `uptime` load average; 5 PX4 SITL instances + Gazebo on one WSL2 VM is a lot, and this gets worse as load climbs. `formation_flight`'s retry loop (every 2s, indefinitely) often succeeds eventually if given enough real time; there is currently no infra-level bypass for this (would require baking a relaxed `COM_ARM_EKF_*`/`CBRK_*` param into `tools/PX4-Autopilot/ROMFS/px4fmu_common/init.d-posix/airframes/4001_gz_x500`, same mechanism already used for the RC failsafe params there — not yet done). |
| Teardown hangs forever on `Waiting for at least 1 matching subscription(s)...` | `ps aux \| grep "ros2 topic pub"`, kill it by PID | The land-command loop at the end of `run_experiment_motion.sh` uses `ros2 topic pub --once`, which blocks indefinitely if it can't discover a subscriber. This is cosmetic — the actual data collection has already finished by this point in the script — but the script won't exit on its own. Safe to `kill -9` the stuck PID; the script continues past it. |
| All CSVs come back with 0 rows even though drones looked fine in QGC | Check each layer bottom-up: `ground_truth_demux` log ("ground truth flowing: N frames" — note this counter increments unconditionally even if nothing actually got republished, so it does *not* prove the ROS2-side publish succeeded), then registry, then `coop_loc_ekf`'s own log (`tmux capture-pane -t <session>:algorithm`, look for `[EKF] Waiting for registry and spawn position...` meaning it's stuck) | Cooperative-localisation fusion is per-drone/per-neighbour, not all-or-nothing (`cooperative_localisation_ekf.py`'s `_tick()` only needs its own registry entry + ≥1 known neighbour, and publishes every tick regardless of how many neighbours currently have fresh ranges) — so one unhealthy drone should not silently zero out the others. If it does, the registry/discovery layer above is the actual cause, not the fusion logic. |
| QGC's "Vehicle N" doesn't seem to match `px4_N` | — | QGC numbers vehicles by MAVLink `target_system`, not by `px4_N` index. The teardown/formation_flight code computes `target_system = int(drone.split("_")[1]) + 1`, so **QGC "Vehicle N" = `px4_(N-1)`** (Vehicle 2 = px4_1, Vehicle 6 = px4_5, etc). Cross-check against `/tmp/px4_N.log` directly rather than trusting QGC's vehicle list when in doubt. |

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
