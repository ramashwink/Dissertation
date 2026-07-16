#!/usr/bin/env python3
"""
Cooperative localisation -- WLS + Tukey bisquare loss (Approach 4).

Tukey's bisquare (biweight) loss HARD-ZEROS the influence of any residual
beyond the tuning constant c.  Unlike Huber (which down-weights but keeps
outliers), Tukey completely ignores measurements whose residual exceeds the
threshold.

Security relevance:
  - Wormhole: the shrunk range creates residuals >>c → completely ignored.
  - Sybil:    ghost measurements inconsistent with the honest majority are
              zeroed out after a few cycles.
  - Replay:   stale measurements that drift far from truth get zeroed.

This is ITERATED REWEIGHTED LEAST SQUARES (IRLS):
  1. Compute residuals with current estimate.
  2. Compute Tukey weights w_i = (1 - (r_i/c)^2)^2  if |r_i| < c, else 0.
  3. Run a WLS step with those weights.
  4. Repeat until convergence.

Tuning:
  TUKEY_C  -- residuals beyond this (metres) get zero weight.
              Rule of thumb: ~4.685 * sigma (sigma = expected noise level).
              At LiDAR noise ~0.05 m → TUKEY_C ≈ 0.25 m.
              Set higher (e.g. 1.0) during initial testing to avoid
              over-rejection on well-behaved measurements.

Usage:
    python3 coop_loc_wls_tukey.py px4_1

CSV log: ~/Dissertation/evidence/metrics/wls_tukey_{ns}.csv
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
TUKEY_C     = 1.0    # metres — residuals beyond this get zero weight
IRLS_ITERS  = 5      # inner IRLS iterations per tick

APPROACH    = "wls_tukey"
LOG_DIR     = os.path.expanduser("~/Dissertation/evidence/metrics")
# ─────────────────────────────────────────────────────────────────────────────


def tukey_weights(residuals, c):
    """Tukey bisquare weights: (1-(r/c)^2)^2 if |r|<c, else 0."""
    r = np.asarray(residuals)
    w = np.where(np.abs(r) < c, (1.0 - (r / c) ** 2) ** 2, 0.0)
    return w


class CoopLocWLSTukey(Node):
    def __init__(self, drone_ns):
        super().__init__(f"coop_loc_wls_tukey_{drone_ns}")
        self.ns         = drone_ns
        self.neighbours = [d for d in DRONES if d != drone_ns]
        self.estimate   = SPAWN_POSITIONS[drone_ns].copy()

        self.latest_range_vec     = {n: None              for n in self.neighbours}
        self.latest_neighbour_pos = {n: SPAWN_POSITIONS[n].copy() for n in self.neighbours}

        for nbr in self.neighbours:
            self.create_subscription(
                PointStamped, f"/{drone_ns}/coop/range_to/{nbr}",
                lambda msg, n=nbr: self._on_range(n, msg), 10)
            self.create_subscription(
                PoseStamped,  f"/{nbr}/coop/self_estimate",
                lambda msg, n=nbr: self._on_neighbour_est(n, msg), 10)

        self.est_pub  = self.create_publisher(PoseStamped, f"/{drone_ns}/coop/self_estimate", 10)
        self.time_pub = self.create_publisher(Float32,     f"/{drone_ns}/coop/solve_time_ms",  10)

        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, f"{APPROACH}_{drone_ns}.csv")
        self._csv_fh  = open(log_path, "w", newline="")
        self._csv_out = csv.writer(self._csv_fh)
        self._csv_out.writerow(["t_sec", "x", "y", "z", "solve_ms", "n_zero_weights"])
        self.get_logger().info(f"Logging to {log_path}")

        self.timer = self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self._t0   = time.monotonic()

    def _on_range(self, nbr, msg):
        self.latest_range_vec[nbr] = np.array([msg.point.x, msg.point.y, msg.point.z])

    def _on_neighbour_est(self, nbr, msg):
        self.latest_neighbour_pos[nbr] = np.array([
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])

    def _tick(self):
        if any(self.latest_range_vec[n] is None for n in self.neighbours):
            return

        t_start = time.perf_counter()
        est, n_zero = self._solve_irls()
        solve_ms = (time.perf_counter() - t_start) * 1e3

        if est is not None:
            self.estimate = est

        self._publish_estimate()
        msg = Float32(); msg.data = float(solve_ms)
        self.time_pub.publish(msg)

        elapsed = time.monotonic() - self._t0
        self._csv_out.writerow([
            f"{elapsed:.3f}",
            f"{self.estimate[0]:.4f}", f"{self.estimate[1]:.4f}", f"{self.estimate[2]:.4f}",
            f"{solve_ms:.3f}", n_zero,
        ])
        self._csv_fh.flush()

    def _solve_irls(self):
        """Iterated Reweighted Least Squares with Tukey bisquare weights."""
        positions     = np.array([self.latest_neighbour_pos[n] for n in self.neighbours])
        observed_vecs = np.array([self.latest_range_vec[n]     for n in self.neighbours])

        p = self.estimate.copy()
        n_zero = 0

        for _ in range(IRLS_ITERS):
            # Residuals at current estimate (flattened across neighbours)
            predicted = positions - p[np.newaxis, :]
            raw_res   = (predicted - observed_vecs).flatten()  # shape (3*N,)

            # Tukey weights — one scalar per component residual
            w = tukey_weights(raw_res, TUKEY_C)
            n_zero = int(np.sum(w == 0.0))

            # Weighted residuals for least_squares (pass sqrt(w) as scale)
            sqrt_w = np.sqrt(w + 1e-12)  # avoid division by zero

            def weighted_residuals(x, sw=sqrt_w, pos=positions, obs=observed_vecs):
                pred = pos - x[np.newaxis, :]
                return sw * (pred - obs).flatten()

            result = least_squares(weighted_residuals, p, method="lm")
            if not result.success:
                return None, n_zero
            p = result.x

        return p, n_zero

    def _publish_estimate(self):
        msg = PoseStamped()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.pose.position.x = float(self.estimate[0])
        msg.pose.position.y = float(self.estimate[1])
        msg.pose.position.z = float(self.estimate[2])
        msg.pose.orientation.w = 1.0
        self.est_pub.publish(msg)

    def destroy_node(self):
        self._csv_fh.close()
        super().destroy_node()


def main():
    drone_ns = sys.argv[1] if len(sys.argv) > 1 else "px4_1"
    if drone_ns not in DRONES:
        print(f"Unknown drone '{drone_ns}'. Choose from {DRONES}"); sys.exit(1)
    rclpy.init()
    node = CoopLocWLSTukey(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
