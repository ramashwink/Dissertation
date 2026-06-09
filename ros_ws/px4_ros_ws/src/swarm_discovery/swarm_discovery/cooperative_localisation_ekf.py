#!/usr/bin/env python3
"""
Cooperative localisation node — EKF edition
=============================================
Drop-in replacement for cooperative_localisation_dynamic.py.
Runs an Extended Kalman Filter instead of batch WLS.

State vector: [px, py, pz, vx, vy, vz]  (6×1)
  - Position + velocity in ENU world frame
  - Velocity allows the predict step to extrapolate between measurements

Predict step (constant-velocity model):
  x_k|k-1 = F · x_k-1
  P_k|k-1 = F · P · Fᵀ + Q
  F = [[I3  dt·I3], [0  I3]]
  Q = process noise (tunable — higher Q = more responsive, less smooth)

Update step (per neighbour measurement):
  Measurement: z = observed relative vector (range + bearing from LiDAR)
  Predicted:   z_hat = neighbour_pos - my_pos  (from state)
  Innovation:  y = z - z_hat
  Jacobian:    H = [-I3 | 0]  (measurement depends on position, not velocity)
  Kalman gain: K = P·Hᵀ·(H·P·Hᵀ + R)⁻¹
  Update:      x = x + K·y,   P = (I - K·H)·P

Same ROS 2 interface as coop_loc_dynamic:
  - Subscribes to /swarm/registry (dynamic neighbour discovery)
  - Subscribes to /px4_N/coop/range_to/{neighbour}
  - Subscribes to /{neighbour}/coop/self_estimate
  - Publishes  /px4_N/coop/self_estimate  (PoseStamped — position only)
  - Publishes  /px4_N/coop/self_estimate_cov (PoseWithCovarianceStamped)

Switch algorithm at launch:
  ros2 run swarm_discovery coop_loc_ekf px4_1
  ros2 run swarm_discovery coop_loc_dynamic px4_1   ← WLS (unchanged)

Run both in parallel for comparison:
  ros2 run swarm_discovery coop_loc_ekf     px4_1 &
  ros2 run swarm_discovery coop_loc_dynamic px4_1 &
  (they publish on different topics — ekf uses /ekf/ prefix)
"""
import sys
import time
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped, PoseStamped
from geometry_msgs.msg import PoseWithCovarianceStamped
from swarm_msgs.msg import SwarmRegistry, SwarmMember

PUBLISH_HZ = 10.0

# ── EKF tuning parameters ────────────────────────────────────────────────────
# Process noise Q — how much we trust the motion model
# Higher = filter reacts faster to changes, noisier output
# Lower  = smoother output, slower to react
Q_POS = 0.01    # position process noise (m²/s)
Q_VEL = 0.1     # velocity process noise (m²/s³)

# Measurement noise R — how much we trust each LiDAR range measurement
# Match to inter_drone_ranging.py noise model:
#   RANGE_SIGMA=0.05m, BEARING_SIGMA=0.0087rad
R_RANGE = 0.05 ** 2    # 0.0025 m²
# ─────────────────────────────────────────────────────────────────────────────


class EKFCooperativeLocalisation(Node):
    def __init__(self, drone_ns: str):
        super().__init__("cooperative_localisation_ekf")
        self.ns = drone_ns

        # ── EKF state ─────────────────────────────────────────────────────
        # x = [px, py, pz, vx, vy, vz]
        self._x = np.zeros(6)
        # P = 6×6 covariance matrix — start with high uncertainty
        self._P = np.eye(6) * 10.0
        self._last_predict_time = None
        self._own_spawn_known   = False

        # ── Dynamic neighbour state (same as coop_loc_dynamic) ────────────
        self._known_members       = {}
        self._range_subs          = {}
        self._est_subs            = {}
        self._latest_range_vec    = {}
        self._latest_neighbour_pos = {}
        self._iteration           = 0

        # ── Subscriptions ─────────────────────────────────────────────────
        self.create_subscription(
            SwarmRegistry, "/swarm/registry", self._on_registry, 10)

        # ── Publishers ────────────────────────────────────────────────────
        # Primary: same topic as WLS so downstream nodes work unchanged
        self._pose_pub = self.create_publisher(
            PoseStamped,
            f"/{drone_ns}/coop/ekf_estimate", 10)

        # Secondary: covariance topic (EKF-only output)
        self._cov_pub = self.create_publisher(
            PoseWithCovarianceStamped,
            f"/{drone_ns}/coop/ekf_estimate_cov", 10)

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().info(
            f"[EKF] {drone_ns} — Q_pos={Q_POS} Q_vel={Q_VEL} R={R_RANGE}")

    # ── Registry callback (identical to coop_loc_dynamic) ─────────────────
    def _on_registry(self, msg: SwarmRegistry):
        incoming = {m.drone_ns: m for m in msg.members}
        for ns, member in incoming.items():
            if ns == self.ns:
                if not self._own_spawn_known:
                    self._x[:3] = [member.spawn_x, member.spawn_y, member.spawn_z]
                    self._own_spawn_known = True
                    self.get_logger().info(
                        f"[EKF] Own spawn: {self._x[:3]}")
                continue
            if ns not in self._known_members:
                self._add_neighbour(ns, member)
        for ns in [n for n in self._known_members if n not in incoming]:
            self._remove_neighbour(ns)

    def _add_neighbour(self, ns, member):
        spawn = np.array([member.spawn_x, member.spawn_y, member.spawn_z])
        self._known_members[ns]          = spawn
        self._latest_range_vec[ns]       = None
        self._latest_neighbour_pos[ns]   = spawn

        range_topic = f"/{self.ns}/coop/range_to/{ns}"
        self._range_subs[range_topic] = self.create_subscription(
            PointStamped, range_topic,
            lambda msg, n=ns: self._on_range(n, msg), 10)

        est_topic = f"/{ns}/coop/self_estimate"
        self._est_subs[est_topic] = self.create_subscription(
            PoseStamped, est_topic,
            lambda msg, n=ns: self._on_neighbour_est(n, msg), 10)

        self.get_logger().info(
            f"[EKF] Added neighbour: {ns} (total: {len(self._known_members)})")

    def _remove_neighbour(self, ns):
        del self._known_members[ns]
        self._latest_range_vec.pop(ns, None)
        self._latest_neighbour_pos.pop(ns, None)
        for d, topic in [
            (self._range_subs, f"/{self.ns}/coop/range_to/{ns}"),
            (self._est_subs,   f"/{ns}/coop/self_estimate")
        ]:
            if topic in d:
                self.destroy_subscription(d.pop(topic))
        self.get_logger().warn(f"[EKF] Removed neighbour: {ns}")

    def _on_range(self, neighbour, msg):
        self._latest_range_vec[neighbour] = np.array([
            msg.point.x, msg.point.y, msg.point.z])

    def _on_neighbour_est(self, neighbour, msg):
        self._latest_neighbour_pos[neighbour] = np.array([
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z])

    # ── EKF predict step ──────────────────────────────────────────────────
    def _predict(self, dt: float):
        """
        Constant-velocity motion model.
        F = [[I3  dt·I3]
             [0    I3  ]]
        """
        F = np.eye(6)
        F[0, 3] = dt
        F[1, 4] = dt
        F[2, 5] = dt

        # Process noise Q
        Q = np.zeros((6, 6))
        Q[0, 0] = Q[1, 1] = Q[2, 2] = Q_POS * dt
        Q[3, 3] = Q[4, 4] = Q[5, 5] = Q_VEL * dt

        self._x = F @ self._x
        self._P = F @ self._P @ F.T + Q

    # ── EKF update step (per neighbour) ───────────────────────────────────
    def _update(self, neighbour_pos: np.ndarray, observed_vec: np.ndarray):
        """
        Measurement model: z = neighbour_pos - my_pos
        Jacobian: H = [-I3 | 0_{3×3}]
          (measurement depends only on position part of state)

        Innovation: y = z_observed - z_predicted
        Kalman gain: K = P·Hᵀ·(H·P·Hᵀ + R)⁻¹
        State update: x = x + K·y
        Cov update:  P = (I - K·H)·P
        """
        # Measurement Jacobian H (3×6)
        H = np.zeros((3, 6))
        H[0, 0] = H[1, 1] = H[2, 2] = -1.0

        # Predicted measurement
        z_pred = neighbour_pos - self._x[:3]

        # Innovation
        y = observed_vec - z_pred

        # Measurement noise
        R = np.eye(3) * R_RANGE

        # Innovation covariance
        S = H @ self._P @ H.T + R

        # Kalman gain
        K = self._P @ H.T @ np.linalg.inv(S)

        # State update
        self._x = self._x + K @ y

        # Covariance update (Joseph form for numerical stability)
        I_KH = np.eye(6) - K @ H
        self._P = I_KH @ self._P @ I_KH.T + K @ R @ K.T

    # ── Main tick ──────────────────────────────────────────────────────────
    def _tick(self):
        if not self._known_members or not self._own_spawn_known:
            if self._iteration % 20 == 0:
                self.get_logger().warn(
                    "[EKF] Waiting for registry and spawn position...")
            self._iteration += 1
            return

        # Predict
        now = time.monotonic()
        if self._last_predict_time is None:
            self._last_predict_time = now
        dt = now - self._last_predict_time
        self._last_predict_time = now

        if dt > 0:
            self._predict(dt)

        # Update — one update call per neighbour with a fresh range
        ready = [
            ns for ns in self._known_members
            if self._latest_range_vec.get(ns) is not None
        ]

        for ns in ready:
            self._update(
                self._latest_neighbour_pos[ns],
                self._latest_range_vec[ns]
            )

        self._publish()
        self._iteration += 1

    # ── Publishers ────────────────────────────────────────────────────────
    def _publish(self):
        stamp = self.get_clock().now().to_msg()
        pos   = self._x[:3]

        # PoseStamped (position only — compatible with WLS output)
        ps = PoseStamped()
        ps.header.stamp    = stamp
        ps.header.frame_id = "world"
        ps.pose.position.x = float(pos[0])
        ps.pose.position.y = float(pos[1])
        ps.pose.position.z = float(pos[2])
        ps.pose.orientation.w = 1.0
        self._pose_pub.publish(ps)

        # PoseWithCovarianceStamped (position + 3×3 covariance)
        pc = PoseWithCovarianceStamped()
        pc.header.stamp    = stamp
        pc.header.frame_id = "world"
        pc.pose.pose.position.x = float(pos[0])
        pc.pose.pose.position.y = float(pos[1])
        pc.pose.pose.position.z = float(pos[2])
        pc.pose.pose.orientation.w = 1.0
        # ROS covariance is 6×6 [x,y,z,rx,ry,rz] row-major
        # Fill position block (top-left 3×3) from P
        cov = [0.0] * 36
        for i in range(3):
            for j in range(3):
                cov[i * 6 + j] = float(self._P[i, j])
        pc.pose.covariance = cov
        self._cov_pub.publish(pc)

        # Log covariance trace every 20 ticks
        if self._iteration % 20 == 0:
            trace = float(np.trace(self._P[:3, :3]))
            self.get_logger().info(
                f"[EKF] pos=[{pos[0]:+.3f},{pos[1]:+.3f},{pos[2]:+.3f}] "
                f"cov_trace={trace:.4f}")


def main():
    ns = sys.argv[1] if len(sys.argv) > 1 else "px4_3"
    rclpy.init()
    node = EKFCooperativeLocalisation(ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
