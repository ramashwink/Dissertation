#!/usr/bin/env python3
"""
arm_all_drones.py
=================
Waits for EKF2 convergence, then arms all 5 drones via force-arm.
Keeps injecting vision position continuously — leave running during experiment.

Terminal 1: bash start_swarm_motion.sh
Terminal 2: python3 arm_all_drones.py   ← leave running
Terminal 3: bash demo_motion.sh ...
"""
from pymavlink import mavutil
import time, sys

PORTS  = {1:18571, 2:18572, 3:18573, 4:18574, 5:18575}
SPAWNS = {1:(0.0,0.0), 2:(2.0,0.0), 3:(4.0,0.0), 4:(2.0,2.0), 5:(4.0,2.0)}

print("Connecting...")
conns = {}
for sysid, port in PORTS.items():
    conns[sysid] = mavutil.mavlink_connection(
        f"udpout:127.0.0.1:{port}", source_system=254)
    time.sleep(0.3)
print("Connected to all 5.")

# Step 1 — inject vision for 15s to converge EKF
print("\nSeeding EKF2 (15s)...")
for tick in range(150):
    t_us = int(time.time() * 1e6)
    for sysid, conn in conns.items():
        x, y = SPAWNS[sysid]
        conn.mav.vision_position_estimate_send(
            t_us, x, y, -0.05, 0.0, 0.0, 0.0)
    time.sleep(0.1)
    if tick % 30 == 0:
        print(f"  {tick//10}s...")

# Step 2 — check each drone's EKF state before arming
print("\nChecking EKF state on each drone...")
for sysid, conn in conns.items():
    conn.mav.command_long_send(
        sysid, 1,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1.0, 0, 0, 0, 0, 0, 0)
    t = time.time()
    while time.time() - t < 2:
        msg = conn.recv_match(blocking=False)
        if msg and msg.get_type() == "STATUSTEXT":
            txt = msg.text.strip()
            if txt:
                print(f"  px4_{sysid}: {txt}")
        time.sleep(0.02)

time.sleep(1)

# Step 3 — force arm all (bypasses remaining checks)
print("\nForce arming all drones...")
for sysid, conn in conns.items():
    conn.mav.command_long_send(
        sysid, 1,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1.0, 21196.0, 0, 0, 0, 0, 0)
    print(f"  px4_{sysid}: force arm sent")
    time.sleep(0.2)

print("\n✓ Armed. Keeping EKF alive — leave this terminal running.")
print("  Now run demo_motion.sh in another terminal.\n")

# Step 4 — continuous vision injection forever
tick = 0
while True:
    t_us = int(time.time() * 1e6)
    for sysid, conn in conns.items():
        x, y = SPAWNS[sysid]
        conn.mav.vision_position_estimate_send(
            t_us, x, y, -0.05, 0.0, 0.0, 0.0)
    time.sleep(0.1)
    tick += 1
    if tick % 100 == 0:
        print(f"  keepalive t={tick//10}s")
