#!/usr/bin/env python3
"""
Cooperative localisation -- RANSAC (Approach 5).

Random Sample Consensus for cooperative position estimation.

Algorithm:
  1. Randomly sample a minimal subset of range measurements (MIN_SAMPLE).
  2. Fit a position using standard WLS on that subset.
  3. Count INLIERS: all other measurements consistent with that position
     within INLIER_THRESHOLD metres.
  4. Repeat for N_ITER iterations.
  5. Return the estimate with the most inliers; refit on all inliers.

Security relevance:
  - Sybil:    ghost measurements are inconsistent with the honest majority
              → they are inliers only in iterations that accidentally sample
              ghost ranges → honest-majority estimate wins.
  - Wormhole: the corrupted pair stands alone → outlier in most iterations.
  - Replay:   stale ranges produce large residuals → rejected as outliers.

RANSAC is naturally suited to environments where the attacker controls a
minority of measurements (< 50%).  With 5 drones and 1 evil drone, the
honest majority is 4/4 range pairs → RANSAC is theoretically robust.

Tuning:
  MIN_SAMPLE       -- minimum neighbours to fit on (>= 2 for 3D: 2*3=6 >= 3)
  N_ITER           -- iterations: higher = better chance of all-honest sample
  INLIER_THRESHOLD -- (metres) residual threshold to count as inlier

Usage:
    python3 coop_loc_ransac.py px4_1

CSV log: ~/Dissertation/evidence/metrics/ransac_{ns}.csv
"""
import csv
import os
import random
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

PUBLISH_HZ        = 10.0
MIN_SAMPLE        = 2      # minimum neighbours in a RANSAC hypothesis
N_ITER            = 20     # RANSAC iterations per tick
INLIER_THRESHOLD  = 0.3    # metres — residual norm below this = inlier

APPROACH = "ransac"
LOG_DIR  = os.path.expanduser("~/Dissertation/evidence/metrics")
# ─────────────────────────────────────────────────────────────────────────────


def _wls_fit(positions, observed_vecs, x0):
    """Standard L2 WLS on a subset of measurements."""
    def residuals(p):
        predicted = positions - p[np.newaxis, :]
        return (predicted - observed_vecs).flatten()

    result = least_squares(residuals, x0, method="lm")
    return result.x if result.success else None


def _count_inliers(p, all_positions, all_observed, threshold):
    """Return mask of measurements consistent with position p."""
    predicted   = all_positions - p[np.newaxis, :]
    per_neighbour_err = np.linalg.norm(predicted - all_observed, axis=1)
    return per_neighbour_err < threshold


class CoopLocRANSAC(Node):
    def __init__(self, drone_ns):
        super().__init__(f"coop_loc_ransac_{drone_ns}")
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
        self._csv_out.writerow(["t_sec", "x", "y", "z", "solve_ms", "best_inliers", "n_neighbours"])
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
        est, best_inliers = self._solve_ransac()
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
            f"{solve_ms:.3f}", best_inliers, len(self.neighbours),
        ])
        self._csv_fh.flush()

    def _solve_ransac(self):
        nbrs          = self.neighbours
        all_positions = np.array([self.latest_neighbour_pos[n] for n in nbrs])
        all_observed  = np.array([self.latest_range_vec[n]     for n in nbrs])
        n             = len(nbrs)

        if n < MIN_SAMPLE:
            # Fall back to standard WLS if too few neighbours
            est = _wls_fit(all_positions, all_observed, self.estimate)
            return est, n

        best_est      = None
        best_inlier_n = -1
        sample_size   = min(MIN_SAMPLE, n)

        for _ in range(N_ITER):
            # Sample a random subset of neighbours
            idx_sample  = random.sample(range(n), sample_size)
            pos_sample  = all_positions[idx_sample]
            obs_sample  = all_observed[idx_sample]

            # Fit position on subset
            hyp = _wls_fit(pos_sample, obs_sample, self.estimate)
            if hyp is None:
                continue

            # Count inliers across ALL neighbours
            inlier_mask = _count_inliers(hyp, all_positions, all_observed, INLIER_THRESHOLD)
            n_inliers   = int(inlier_mask.sum())

            if n_inliers > best_inlier_n:
                best_inlier_n = n_inliers
                # Refit on all inliers for a better estimate
                if n_inliers >= MIN_SAMPLE:
                    best_est = _wls_fit(
                        all_positions[inlier_mask],
                        all_observed[inlier_mask],
                        hyp,
                    )
                else:
                    best_est = hyp

        return best_est, best_inlier_n

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
    node = CoopLocRANSAC(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
