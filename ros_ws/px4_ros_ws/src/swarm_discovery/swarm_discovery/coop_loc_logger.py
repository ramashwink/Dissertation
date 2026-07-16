#!/usr/bin/env python3
"""
coop_loc_logger.py
==================
External CSV logger for WLS and EKF nodes that have no built-in logging.

Subscribes to /{drone}/coop/self_estimate (or /ekf_estimate for EKF)
and writes the same CSV format as the mitigation nodes so analyse_all_approaches.py
can read them consistently.

Usage:
    # Log WLS for all 5 drones:
    python3 coop_loc_logger.py wls px4_1 &
    python3 coop_loc_logger.py wls px4_2 &
    ...

    # Log EKF for all 5 drones:
    python3 coop_loc_logger.py ekf px4_1 &
    ...

Output:
    ~/Dissertation/evidence/metrics/wls_px4_N.csv
    ~/Dissertation/evidence/metrics/ekf_px4_N.csv

CSV columns: t_sec, x, y, z, solve_ms
  (solve_ms is always 0.0 for WLS/EKF since they don't publish timing;
   timing comes from ekf_attack_logger for EKF, or use perf_counter below)
"""
import csv
import os
import sys
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped

DRONES   = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
LOG_DIR  = os.path.expanduser("~/Dissertation/evidence/metrics")

# Topic map: approach -> topic suffix per drone
TOPIC_MAP = {
    "wls": "coop/self_estimate",     # published by coop_loc_dynamic
    "ekf": "coop/ekf_estimate",      # published by coop_loc_ekf
}


class CoopLocLogger(Node):
    def __init__(self, approach, drone_ns):
        super().__init__(f"coop_loc_logger_{approach}_{drone_ns}")
        self.approach = approach
        self.ns       = drone_ns

        topic_suffix = TOPIC_MAP.get(approach)
        if topic_suffix is None:
            self.get_logger().error(f"Unknown approach '{approach}'. Choose: wls, ekf")
            sys.exit(1)

        topic = f"/{drone_ns}/{topic_suffix}"

        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, f"{approach}_{drone_ns}.csv")
        self._fh  = open(log_path, "w", newline="")
        self._csv = csv.writer(self._fh)
        self._csv.writerow(["t_sec", "x", "y", "z", "solve_ms"])
        self._t0  = time.monotonic()
        self._count = 0

        self.create_subscription(PoseStamped, topic, self._on_estimate, 10)
        self.get_logger().info(f"Logging {topic} -> {log_path}")

    def _on_estimate(self, msg):
        t = time.monotonic() - self._t0
        x = msg.pose.position.x
        y = msg.pose.position.y
        z = msg.pose.position.z
        self._csv.writerow([f"{t:.4f}", f"{x:.6f}", f"{y:.6f}", f"{z:.6f}", "0.000"])
        self._fh.flush()
        self._count += 1
        if self._count % 100 == 0:
            self.get_logger().info(f"{self.ns}: {self._count} rows logged")

    def destroy_node(self):
        self._fh.close()
        self.get_logger().info(f"Logger closed. Total rows: {self._count}")
        super().destroy_node()


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 coop_loc_logger.py <approach> <drone_ns>")
        print("  approach: wls | ekf")
        print("  drone_ns: px4_1 | px4_2 | px4_3 | px4_4 | px4_5")
        sys.exit(1)

    approach = sys.argv[1]
    drone_ns = sys.argv[2]

    if drone_ns not in DRONES:
        print(f"Unknown drone '{drone_ns}'. Choose from {DRONES}")
        sys.exit(1)

    rclpy.init()
    node = CoopLocLogger(approach, drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
