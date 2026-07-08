#!/usr/bin/env python3
"""
set_rc_params.py
================
Sets COM_RC_IN_MODE=4 and related failsafe params on all 5 drones.
Run once after start_swarm_motion.sh, before arming.
Called automatically by start_swarm_motion.sh.
"""
from pymavlink import mavutil
import time

PORTS = {1: 18571, 2: 18572, 3: 18573, 4: 18574, 5: 18575}

PARAMS = [
    (b'COM_RC_IN_MODE',  4,   6),   # No RC required — MAVLink commands accepted
    (b'NAV_RCL_ACT',     0,   6),   # RC loss action: none
    (b'COM_RCL_EXCEPT',  31,  6),   # RC loss ignored in all modes
    (b'GF_ACTION',       0,   6),   # Geofence breach: none
    (b'COM_RC_LOSS_T',   10,  9),   # RC loss timeout: 10s (float)
    (b'NAV_DLL_ACT',     0,   6),   # Datalink loss action: none — no GCS required to arm
    (b'COM_LOW_BAT_ACT', 0,   6),   # Low battery action: warning only — no RTL/land during long batches
    (b'SIM_BAT_DRAIN',   0,   9),   # Disable SITL battery simulator entirely (float; 0 = module doesn't start)
    (b'COM_OF_LOSS_T',   5.0, 9),   # Offboard-loss timeout: 5s (default 1s) — tolerate setpoint-stream
                                    # gaps during heavy multi-instance boot CPU/DDS contention instead
                                    # of failsafe-switching to Position mode mid-arm.
]

print("[RC-PARAMS] Connecting to all 5 drones...")
for sysid, port in PORTS.items():
    try:
        conn = mavutil.mavlink_connection(
            f"udpout:127.0.0.1:{port}", source_system=254)
        time.sleep(0.4)
        for name, val, ptype in PARAMS:
            conn.mav.param_set_send(sysid, 1, name, val, ptype)
            time.sleep(0.05)
        print(f"  px4_{sysid}: COM_RC_IN_MODE=4, NAV_RCL_ACT=0, "
              f"COM_RCL_EXCEPT=31, GF_ACTION=0, COM_RC_LOSS_T=10 ✓")
    except Exception as e:
        print(f"  px4_{sysid}: FAILED — {e}")

print("[RC-PARAMS] Done — drones will not RTL on RC loss.")
