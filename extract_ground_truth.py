#!/usr/bin/env python3
"""
extract_ground_truth.py  (v3 — model names fixed for x500_N)
=============================================================
Gazebo publishes models as x500_1..x500_5, not px4_1..px4_5.
This version maps x500_N -> px4_N before writing CSVs.

Run IN A SEPARATE TERMINAL while your localisation stack is running.
Ctrl-C after ~60-120 s.

Usage:
  python3 extract_ground_truth.py              # all 5 drones
  python3 extract_ground_truth.py px4_1        # single drone

Output: ~/Dissertation/evidence/gt/gt_px4_N.csv  (columns: t_sec, x, y, z)
"""
import csv, os, sys, time, threading

DRONES        = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
GT_DIR        = os.path.expanduser("~/Dissertation/evidence/gt")
GZ_POSE_TOPIC = "/world/default/dynamic_pose/info"

# Gazebo model name -> drone namespace
# x500_1 -> px4_1, x500_2 -> px4_2, etc.
MODEL_TO_DRONE = {f"x500_{i}": f"px4_{i}" for i in range(1, 6)}


def main():
    requested = sys.argv[1:] if len(sys.argv) > 1 else DRONES
    invalid   = [d for d in requested if d not in DRONES]
    if invalid:
        print(f"Unknown drones: {invalid}. Choose from {DRONES}"); sys.exit(1)

    # Only map models for requested drones
    active_map = {gz: ros for gz, ros in MODEL_TO_DRONE.items() if ros in requested}

    try:
        from gz.transport13 import Node as GzNode
        from gz.msgs10.pose_v_pb2 import Pose_V
    except ImportError:
        print("ERROR: gz-transport not available.")
        print("  sudo apt install python3-gz-transport13 python3-gz-msgs10")
        sys.exit(1)

    os.makedirs(GT_DIR, exist_ok=True)
    files, writers = {}, {}
    for gz_name, drone in active_map.items():
        path = os.path.join(GT_DIR, f"gt_{drone}.csv")
        fh   = open(path, "w", newline="")
        w    = csv.writer(fh)
        w.writerow(["t_sec", "x", "y", "z"])
        files[drone]   = fh
        writers[drone] = w
        print(f"  {gz_name} -> {drone} -> {path}")

    lock = threading.Lock()
    t0   = time.monotonic()
    counts = {d: 0 for d in requested}

    def cb(msg):
        t = time.monotonic() - t0
        with lock:
            for pose in msg.pose:
                drone = active_map.get(pose.name)
                if drone:
                    writers[drone].writerow([
                        f"{t:.4f}",
                        f"{pose.position.x:.6f}",
                        f"{pose.position.y:.6f}",
                        f"{pose.position.z:.6f}",
                    ])
                    files[drone].flush()
                    counts[drone] += 1

    node = GzNode()
    node.subscribe(Pose_V, GZ_POSE_TOPIC, cb)

    print(f"\nLogging GT (x500_N -> px4_N). Ctrl-C to stop.\n")
    try:
        last_print = 0
        while True:
            time.sleep(0.5)
            now = time.monotonic() - t0
            if now - last_print >= 5.0:
                with lock:
                    row = "  ".join(f"{d}:{counts[d]}" for d in requested)
                print(f"  t={now:.0f}s  samples: {row}")
                last_print = now
    except KeyboardInterrupt:
        pass

    for fh in files.values():
        fh.close()

    print(f"\nDone. Rows written:")
    for d in requested:
        print(f"  {d}: {counts[d]} rows -> {GT_DIR}/gt_{d}.csv")

    if all(counts[d] == 0 for d in requested):
        print("\nWARNING: No data written! Is SITL running?")
        print("Check model names with:")
        print("  python3 -c \"from gz.transport13 import Node; from gz.msgs10.pose_v_pb2 import Pose_V; "
              "import time,threading; s=set(); l=threading.Lock(); "
              "cb=lambda m: [s.add(p.name) for p in m.pose]; "
              "n=Node(); n.subscribe(Pose_V,'/world/default/dynamic_pose/info',cb); "
              "time.sleep(3); print(sorted(s))\"")
    else:
        print("\nRun analyser:")
        for d in requested:
            print(f"  python3 ~/Dissertation/analyse_all_approaches.py "
                  f"--drone {d} --gt-csv {GT_DIR}/gt_{d}.csv")


if __name__ == "__main__":
    main()
