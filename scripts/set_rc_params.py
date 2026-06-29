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
