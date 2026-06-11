#!/usr/bin/env python3
"""
Cooperative localisation -- WLS + Huber loss (Approach 3).

Identical to the baseline WLS node but replaces the standard L2 (linear)
loss with Huber loss inside scipy least_squares.  Huber acts as L2 for
small residuals and L1 for large ones, down-weighting (but NOT hard-
zeroing) outlier measurements.

Security relevance:
  - Sybil:    partially mitigated — ghost measurements are down-weighted
              if their residuals are large relative to honest measurements.
  - Replay:   partially mitigated — stale ranges produce large residuals
              → Huber down-weights them.
  - Wormhole: partially mitigated — the 5%-range shrink creates a very
              large residual on that pair; Huber reduces its influence.

Tuning:
  f_scale (δ) is the residual threshold between L2 and L1 regimes.
  Set to half the expected noise level (~0.1 m for LiDAR → f_scale=0.5).
  Decrease to be more aggressive (closer to L1 everywhere).

Usage (same as baseline):
    python3 coop_loc_wls_huber.py px4_1
    python3 coop_loc_wls_huber.py px4_2
    ...

Publishes:
    /{ns}/coop/self_estimate   (PoseStamped)
    /{ns}/coop/solve_time_ms   (Float32) -- per-cycle solve latency for RQ2

CSV log: ~/Dissertation/evidence/metrics/wls_huber_{ns}.csv
"""
import csv
import os
import sys
import time
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped, PoseStamped
from std_msgs.msg import Float32
from scipy.optimize import least_squares

# ── Swarm configuration ──────────────────────────────────────────────────────
DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

SPAWN_POSITIONS = {
    "px4_1": np.array([0.0,  0.0, 0.0]),
    "px4_2": np.array([2.0,  0.0, 0.0]),
    "px4_3": np.array([4.0,  0.0, 0.0]),
    "px4_4": np.array([2.0,  2.0, 0.0]),
    "px4_5": np.array([4.0,  2.0, 0.0]),
}

PUBLISH_HZ  = 10.0
HUBER_DELTA = 0.5   # f_scale parameter (metres) — tweak per experiment

APPROACH    = "wls_huber"
LOG_DIR     = os.path.expanduser("~/Dissertation/evidence/metrics")
# ─────────────────────────────────────────────────────────────────────────────


class CoopLocWLSHuber(Node):
    def __init__(self, drone_ns):
        super().__init__(f"coop_loc_wls_huber_{drone_ns}")
        self.ns         = drone_ns
        self.neighbours = [d for d in DRONES if d != drone_ns]
        self.estimate   = SPAWN_POSITIONS[drone_ns].copy()

        self.latest_range_vec    = {n: None              for n in self.neighbours}
        self.latest_neighbour_pos = {n: SPAWN_POSITIONS[n].copy() for n in self.neighbours}

        # ── Subscriptions ────────────────────────────────────────────────────
        for nbr in self.neighbours:
            self.create_subscription(
                PointStamped, f"/{drone_ns}/coop/range_to/{nbr}",
                lambda msg, n=nbr: self._on_range(n, msg), 10)
            self.create_subscription(
                PoseStamped,  f"/{nbr}/coop/self_estimate",
                lambda msg, n=nbr: self._on_neighbour_est(n, msg), 10)

        # ── Publishers ───────────────────────────────────────────────────────
        self.est_pub   = self.create_publisher(PoseStamped, f"/{drone_ns}/coop/self_estimate", 10)
        self.time_pub  = self.create_publisher(Float32,     f"/{drone_ns}/coop/solve_time_ms", 10)

        # ── CSV logger ───────────────────────────────────────────────────────
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, f"{APPROACH}_{drone_ns}.csv")
        self._csv_fh  = open(log_path, "w", newline="")
        self._csv_out = csv.writer(self._csv_fh)
        self._csv_out.writerow(["t_sec", "x", "y", "z", "solve_ms"])
        self.get_logger().info(f"Logging to {log_path}")

        self.timer = self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self._t0   = time.monotonic()

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def _on_range(self, nbr, msg):
        self.latest_range_vec[nbr] = np.array([msg.point.x, msg.point.y, msg.point.z])

    def _on_neighbour_est(self, nbr, msg):
        self.latest_neighbour_pos[nbr] = np.array([
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])

    # ── Solve loop ────────────────────────────────────────────────────────────
    def _tick(self):
        if any(self.latest_range_vec[n] is None for n in self.neighbours):
            return

        t_start = time.perf_counter()
        est     = self._solve()
        solve_ms = (time.perf_counter() - t_start) * 1e3

        if est is not None:
            self.estimate = est

        self._publish_estimate()
        self._publish_solve_time(solve_ms)

        elapsed = time.monotonic() - self._t0
        self._csv_out.writerow([
            f"{elapsed:.3f}",
            f"{self.estimate[0]:.4f}",
            f"{self.estimate[1]:.4f}",
            f"{self.estimate[2]:.4f}",
            f"{solve_ms:.3f}",
        ])
        self._csv_fh.flush()

    def _solve(self):
        positions     = np.array([self.latest_neighbour_pos[n] for n in self.neighbours])
        observed_vecs = np.array([self.latest_range_vec[n]     for n in self.neighbours])

        def residuals(p):
            predicted = positions - p[np.newaxis, :]
            return (predicted - observed_vecs).flatten()

        # KEY CHANGE vs baseline: loss='huber', f_scale=HUBER_DELTA
        result = least_squares(
            residuals, self.estimate,
            method="trf",           # trf required for robust losses (not lm)
            loss="huber",
            f_scale=HUBER_DELTA,
        )
        return result.x if result.success else None

    def _publish_estimate(self):
        msg = PoseStamped()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.pose.position.x = float(self.estimate[0])
        msg.pose.position.y = float(self.estimate[1])
        msg.pose.position.z = float(self.estimate[2])
        msg.pose.orientation.w = 1.0
        self.est_pub.publish(msg)

    def _publish_solve_time(self, ms):
        msg = Float32(); msg.data = float(ms)
        self.time_pub.publish(msg)

    def destroy_node(self):
        self._csv_fh.close()
        super().destroy_node()


def main():
    drone_ns = sys.argv[1] if len(sys.argv) > 1 else "px4_1"
    if drone_ns not in DRONES:
        print(f"Unknown drone '{drone_ns}'. Choose from {DRONES}"); sys.exit(1)
    rclpy.init()
    node = CoopLocWLSHuber(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
