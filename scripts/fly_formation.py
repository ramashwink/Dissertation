#!/usr/bin/env python3
"""
fly_formation.py
================
Commands all 5 SITL drones to fly a coordinated square formation
using MAVLink via pymavlink.

Each drone flies a square of side LENGTH metres at height ALT metres,
offset by their spawn position so they maintain formation spacing.

Usage:
    python3 fly_formation.py              # fly full square
    python3 fly_formation.py --circle     # fly circle instead
    python3 fly_formation.py --hover 30   # hover at ALT for 30s then land
"""
import time
import argparse
import threading
from pymavlink import mavutil

ALT    = 5.0    # metres above home
LENGTH = 8.0    # square side length in metres
SPEED  = 1.5    # m/s

# SITL UDP ports for each drone instance
PORTS = {
    "px4_1": 14550,
    "px4_2": 14551,
    "px4_3": 14552,
    "px4_4": 14553,
    "px4_5": 14554,
}

# Formation offsets (match your spawn grid)
OFFSETS = {
    "px4_1": (0.0, 0.0),
    "px4_2": (2.0, 0.0),
    "px4_3": (4.0, 0.0),
    "px4_4": (2.0, 2.0),
    "px4_5": (4.0, 2.0),
}

def connect(name, port):
    conn = mavutil.mavlink_connection(f"udp:127.0.0.1:{port}")
    conn.wait_heartbeat(timeout=10)
    print(f"[{name}] Connected (system {conn.target_system})")
    return conn

def arm_and_takeoff(conn, name, alt):
    # Set mode to GUIDED
    conn.set_mode("GUIDED")
    time.sleep(1)
    # Arm
    conn.arducopter_arm()
    print(f"[{name}] Armed")
    time.sleep(2)
    # Takeoff
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        0, 0, 0, 0, 0, 0, 0, alt)
    print(f"[{name}] Taking off to {alt}m")
    time.sleep(8)  # wait for takeoff

def goto_ned(conn, name, north, east, down=-5.0):
    conn.mav.send(mavutil.mavlink.MAVLink_set_position_target_local_ned_message(
        0, conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_FRAME_LOCAL_NED,
        0b0000111111111000,  # position only
        north, east, down,
        0, 0, 0, 0, 0, 0, 0, 0))
    print(f"[{name}] → N={north:.1f} E={east:.1f}")

def fly_square(conn, name, ox, oy, length, alt, dwell=5):
    """Fly a square pattern offset by (ox, oy) from home."""
    waypoints = [
        (ox,          oy,          -alt),
        (ox + length, oy,          -alt),
        (ox + length, oy + length, -alt),
        (ox,          oy + length, -alt),
        (ox,          oy,          -alt),
    ]
    for n, e, d in waypoints:
        goto_ned(conn, name, n, e, d)
        time.sleep(dwell)

def land(conn, name):
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_NAV_LAND,
        0, 0, 0, 0, 0, 0, 0, 0)
    print(f"[{name}] Landing")

def drone_mission(name, port, args):
    try:
        conn = connect(name, port)
        ox, oy = OFFSETS[name]
        arm_and_takeoff(conn, name, ALT)

        if args.hover:
            print(f"[{name}] Hovering for {args.hover}s")
            time.sleep(args.hover)
        else:
            fly_square(conn, name, ox, oy, LENGTH, ALT)

        land(conn, name)
    except Exception as e:
        print(f"[{name}] ERROR: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hover", type=int, default=0,
                        help="Hover for N seconds instead of flying square")
    parser.add_argument("--drone", default=None,
                        help="Fly only this drone (e.g. px4_1)")
    args = parser.parse_args()

    targets = {args.drone: PORTS[args.drone]} if args.drone else PORTS

    threads = []
    for name, port in targets.items():
        t = threading.Thread(target=drone_mission, args=(name, port, args))
        t.daemon = True
        threads.append(t)

    print(f"Starting {len(threads)} drone missions simultaneously...")
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("All missions complete.")

if __name__ == "__main__":
    main()
