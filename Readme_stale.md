# PX4 EKF2 External Vision Timestamp Exploit
## Branch: `px4-ekf2-mavlink-exploit`

**Dissertation:** When Drones Go Blind — COMSM0117, University of Bristol, 2026  
**Author:** Ashwin Kotharamath  
**Scope:** Research only — local PX4 SITL instance, no network connectivity

---

## Vulnerability Summary

**Location:** PX4-Autopilot v1.18, two files:

```
src/modules/mavlink/mavlink_receiver.cpp:1457
    odom.timestamp_sample = _mavlink_timesync.sync_stamp(vpe.usec);
    // ↑ vpe.usec passed directly from MAVLink — no age check

src/modules/ekf2/EKF/estimator_interface.cpp:384-398
    const int64_t time_us = evdata.time_us - ekf2_ev_delay*1000
    if (time_us >= newest_buffer + min_obs_interval):
        ACCEPT  // ← only check: not too fast. NO max-age check.
    else:
        WARN "EV data too fast"
```

**Root cause:** EKF2's external vision pipeline validates that measurements
don't arrive *too fast* (minimum interval between samples) but has no
upper bound on measurement age. Messages from arbitrarily far in the past
are accepted and fused into the EKF state.

**Impact:** An attacker with MAVLink access can:
1. Inject replay attacks using captured position data from previous sessions
2. Freeze a drone's EKF2 position estimate at a historical location
3. Slowly drift the EKF2 state toward an attacker-controlled position

**Affected versions:** PX4 v1.18 (confirmed). Likely earlier versions too.

**Prerequisites for fusion:**
- `EKF2_EV_CTRL` must have bit 0 set (horizontal position fusion enabled)
- `EKF2_GPS_CTRL` should be 0 or low to give EV priority
- MAVLink access to port 14570 (px4_1), 14580 (px4_2), etc.

---

## Files

| File | Purpose |
|---|---|
| `px4_ekf2_timestamp_exploit.py` | Main exploit — 3 attack modes |
| `verify_exploit.py` | ULog analysis — proves EKF2 fused the messages |
| `setup_ekf2_ev.sh` | One-time EKF2 parameter setup via QGroundControl |
| `README.md` | This file |

---

## Setup

### Step 1 — Install dependencies
```bash
pip install --user pymavlink pyulog numpy
```

### Step 2 — Enable EKF2 external vision fusion
This is required for VISION_POSITION_ESTIMATE to affect EKF2 state.
Either use QGroundControl Parameters editor, or run:
```bash
# While PX4 SITL is running for px4_1
python3 px4_ekf2_timestamp_exploit.py --drone px4_1 --mode ancient --set-params
```

Parameters to set:
```
EKF2_EV_CTRL = 1    # bit 0: horizontal position fusion
EKF2_GPS_CTRL = 0   # disable GPS so EV dominates
EKF2_HGT_REF = 3    # height reference = vision
```

### Step 3 — Start PX4 SITL
```bash
bash ~/Dissertation/scripts/start_swarm.sh
```

### Step 4 — Run the exploit
```bash
# Single drone, ancient timestamp mode
python3 px4_ekf2_timestamp_exploit.py --drone px4_1 --mode ancient

# All 5 drones simultaneously
python3 px4_ekf2_timestamp_exploit.py --all --mode frozen

# Position drift with current timestamps
python3 px4_ekf2_timestamp_exploit.py --drone px4_1 --mode drift --set-params
```

### Step 5 — Verify fusion
```bash
# Automatically finds latest log
python3 verify_exploit.py

# Specify log file
python3 verify_exploit.py --log ~/Dissertation/tools/PX4-Autopilot/build/px4_sitl_default/rootfs/log/2026-06-17/13_00_45.ulg

# Compare baseline vs exploit
python3 verify_exploit.py --baseline baseline.ulg --exploit exploit.ulg
```

---

## Attack Modes

### Mode A — Ancient (timestamp staleness PoC)
Injects `VISION_POSITION_ESTIMATE` with `usec=1` (Unix epoch, ~56 years ago).
Messages increment by 100ms each so they satisfy the min-interval check.
**Proves:** EKF2 accepts timestamps far beyond any reasonable sensor delay.

```bash
python3 px4_ekf2_timestamp_exploit.py --drone px4_1 --mode ancient
```

Expected output in verify_exploit.py:
```
[!] VULNERABILITY CONFIRMED
[!] PX4 accepted messages 56.X YEARS stale
```

### Mode B — Frozen (replay from previous session)
Replays a fixed position starting at ANCIENT_USEC, incrementing 100ms/msg.
Simulates capturing position data from a previous flight session and
replaying it to freeze the drone's EKF2 state at the historical location.

```bash
python3 px4_ekf2_timestamp_exploit.py --drone px4_1 --mode frozen
```

### Mode C — Drift (position spoofing with valid timestamps)
Injects a drifting false position using current timestamps. Demonstrates
full position spoofing when EV fusion weight exceeds GPS.
Drone position controller will attempt to fly to the spoofed location.

```bash
python3 px4_ekf2_timestamp_exploit.py --drone px4_1 --mode drift --set-params
```

---

## Evidence Chain

For dissertation/responsible disclosure, the evidence chain is:

1. **Source code** — `mavlink_receiver.cpp:1457` + `estimator_interface.cpp:384-398`
   shows no max-age check in the EV pipeline

2. **Exploit output** — `/tmp/px4_ekf2_exploit_px4_1_ancient_*.csv`
   shows injected timestamps and their computed age

3. **ULog verification** — `verify_exploit.py` output shows:
   - `vehicle_visual_odometry.timestamp_sample` matches injected usec
   - `estimator_aid_src_ev_pos` shows EKF2 processed the measurement
   - `vehicle_local_position` shows position drift if EV weight > GPS

---

## Mitigation

**Proposed fix in `estimator_interface.cpp`:**

```cpp
void EstimatorInterface::setExtVisionData(const extVisionSample &evdata)
{
    const uint64_t now_us = hrt_absolute_time();
    
    // ADD: freshness check — reject measurements older than EKF2_EV_MAX_AGE_MS
    const int64_t age_us = static_cast<int64_t>(now_us) 
                           - static_cast<int64_t>(evdata.time_us);
    const int64_t max_age_us = static_cast<int64_t>(_params.ekf2_ev_max_age * 1000);
    
    if (age_us > max_age_us) {
        ECL_WARN("EV data too stale: age=%" PRIi64 "us > max=%" PRIi64 "us",
                 age_us, max_age_us);
        return;  // ← reject stale measurement
    }
    
    // existing code continues...
```

**New parameter needed:**
```yaml
EKF2_EV_MAX_AGE:
  description: Maximum age of external vision measurements (ms)
  default: 500   # 500ms — reasonable for vision systems
  min: 50
  max: 5000
```

---

## Responsible Disclosure Status

- [ ] Exploit developed and tested (this branch)
- [ ] Verified against PX4 v1.18 SITL
- [ ] Supervisor review (Dr. Gardiner / Dr. Oracevic)
- [ ] Decision on disclosure to PX4 project
- [ ] If disclosing: report to security@px4.io or GitHub Security Advisory

**Note:** This finding applies to PX4's MAVLink external vision interface
and is independent of the cooperative localisation stack vulnerability
(Finding F3a) documented in the main dissertation.
