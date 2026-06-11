#!/usr/bin/env python3
"""
Cooperative localisation -- EKF + χ² gating + Huber (Approach 6 / Bold).

This is the dissertation's primary proposed mitigation.  It combines:

  1. Extended Kalman Filter (EKF) for state prediction and covariance
     propagation — provides a principled uncertainty model.

  2. χ² (chi-squared) innovation gating — before assimilating any range
     measurement, its Mahalanobis distance from the predicted state is
     tested against a χ² threshold.  Measurements that fail the gate are
     REJECTED outright (not just down-weighted).

  3. Huber-weighted update — measurements that PASS the gate are still
     incorporated with Huber weights in the EKF update step, providing
     further robustness to heavy-tailed noise.

Security relevance:
  - Replay:    stale ranges cause large innovations → χ² gate rejects them.
  - Wormhole:  5%-shrunk range creates a large Mahalanobis distance → gate.
  - Sybil:     ghost position broadcasts are inconsistent with EKF prediction
               → gated out; χ² threshold tuned to swarm noise level.

EKF state vector:  x = [px, py, pz]  (position only, constant-velocity
                   process model is an extension left for future work).
Process model:     identity (position does not change between ticks at
                   hover; add velocity terms once in-flight).
Observation model: h(x) = x_neighbour - x  (relative position vector)

Tuning:
  PROCESS_NOISE_STD  -- (m) random walk noise per tick (e.g. 0.01 m)
  MEAS_NOISE_STD     -- (m) LiDAR measurement noise per axis (e.g. 0.05 m)
  CHI2_THRESHOLD     -- χ²(dof=3, p=0.95) ≈ 7.815; increase to be more
                        permissive, decrease to be more aggressive.
  HUBER_DELTA        -- (m) Huber threshold applied AFTER gating

Usage:
    python3 coop_loc_ekf_chi2_huber.py px4_1

CSV log: ~/Dissertation/evidence/metrics/ekf_chi2_huber_{ns}.csv
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

# ── Swarm configuration ──────────────────────────────────────────────────────
DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

SPAWN_POSITIONS = {
    "px4_1": np.array([0.0,  0.0, 0.0]),
    "px4_2": np.array([2.0,  0.0, 0.0]),
    "px4_3": np.array([4.0,  0.0, 0.0]),
    "px4_4": np.array([2.0,  2.0, 0.0]),
    "px4_5": np.array([4.0,  2.0, 0.0]),
}

PUBLISH_HZ         = 10.0
PROCESS_NOISE_STD  = 0.01   # metres per tick (random walk)
MEAS_NOISE_STD     = 0.05   # metres per axis (LiDAR noise)
CHI2_THRESHOLD     = 7.815  # χ²(3 dof, p=0.95)
HUBER_DELTA        = 0.5    # metres — Huber threshold for accepted measurements

APPROACH = "ekf_chi2_huber"
LOG_DIR  = os.path.expanduser("~/Dissertation/evidence/metrics")
# ─────────────────────────────────────────────────────────────────────────────


class CoopLocEKFChi2Huber(Node):
    def __init__(self, drone_ns):
        super().__init__(f"coop_loc_ekf_chi2_{drone_ns}")
        self.ns         = drone_ns
        self.neighbours = [d for d in DRONES if d != drone_ns]

        # ── EKF state ────────────────────────────────────────────────────────
        self.x  = SPAWN_POSITIONS[drone_ns].copy()        # state: [px, py, pz]
        self.P  = np.eye(3) * 1.0                         # initial covariance

        # Noise matrices
        self.Q  = np.eye(3) * (PROCESS_NOISE_STD ** 2)   # process noise
        self.R  = np.eye(3) * (MEAS_NOISE_STD   ** 2)    # measurement noise

        # ── Data buffers ─────────────────────────────────────────────────────
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
        self._csv_out.writerow([
            "t_sec", "x", "y", "z", "solve_ms",
            "n_passed_gate", "n_rejected_gate", "trace_P"
        ])
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
        n_pass, n_rej = self._ekf_update()
        solve_ms = (time.perf_counter() - t_start) * 1e3

        self._publish_estimate()
        msg_t = Float32(); msg_t.data = float(solve_ms)
        self.time_pub.publish(msg_t)

        elapsed = time.monotonic() - self._t0
        self._csv_out.writerow([
            f"{elapsed:.3f}",
            f"{self.x[0]:.4f}", f"{self.x[1]:.4f}", f"{self.x[2]:.4f}",
            f"{solve_ms:.3f}", n_pass, n_rej, f"{np.trace(self.P):.6f}",
        ])
        self._csv_fh.flush()

    def _ekf_update(self):
        """
        EKF predict + sequential update with χ² gating and Huber weighting.

        Uses sequential (one-at-a-time) measurement processing so each
        neighbour range can be individually gated.
        """
        # ── Predict ──────────────────────────────────────────────────────────
        # Process model: F = I (stationary hover assumption)
        x_pred = self.x.copy()
        P_pred = self.P + self.Q

        x  = x_pred.copy()
        P  = P_pred.copy()
        n_pass = 0
        n_rej  = 0

        # ── Sequential update per neighbour ──────────────────────────────────
        for nbr in self.neighbours:
            p_nbr = self.latest_neighbour_pos[nbr]   # neighbour's position
            z     = self.latest_range_vec[nbr]        # observed relative vector

            # Observation model: h(x) = p_nbr - x
            # Jacobian H = -I_3  (d/dx [p_nbr - x] = -I)
            H  = -np.eye(3)
            z_pred = p_nbr - x                       # predicted observation

            # Innovation
            y = z - z_pred                           # innovation vector (3,)

            # Innovation covariance
            S = H @ P @ H.T + self.R                 # (3,3)

            # ── χ² gate ──────────────────────────────────────────────────────
            try:
                S_inv = np.linalg.inv(S)
            except np.linalg.LinAlgError:
                n_rej += 1
                continue

            mahal_sq = float(y @ S_inv @ y)

            if mahal_sq > CHI2_THRESHOLD:
                # Measurement rejected — too far from prediction
                n_rej += 1
                self.get_logger().debug(
                    f"[gate] rejected {nbr}: mahal²={mahal_sq:.2f} > {CHI2_THRESHOLD}")
                continue

            n_pass += 1

            # ── Huber weight ─────────────────────────────────────────────────
            # Scale the measurement noise covariance by a Huber-inspired
            # scalar weight based on the innovation norm.
            innov_norm = np.linalg.norm(y)
            if innov_norm <= HUBER_DELTA:
                huber_w = 1.0
            else:
                huber_w = HUBER_DELTA / innov_norm   # down-weight large innovations

            R_robust = self.R / (huber_w + 1e-12)    # inflate R for down-weighted measurements

            # ── Standard EKF update with robust R ────────────────────────────
            S_robust = H @ P @ H.T + R_robust
            K        = P @ H.T @ np.linalg.inv(S_robust)   # Kalman gain (3,3)
            x        = x + K @ y
            P        = (np.eye(3) - K @ H) @ P

        self.x = x
        self.P = P
        return n_pass, n_rej

    def _publish_estimate(self):
        msg = PoseStamped()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.pose.position.x = float(self.x[0])
        msg.pose.position.y = float(self.x[1])
        msg.pose.position.z = float(self.x[2])
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
    node = CoopLocEKFChi2Huber(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
