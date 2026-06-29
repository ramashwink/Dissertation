#!/usr/bin/env python3
"""
ekf_position_bridge.py (revised v2)
=====================================
Bridges PX4 EKF2 odometry output → vehicle_visual_odometry input.
Keeps EKF2 position-valid during motion by re-feeding its own fused
position estimate as a visual odometry source.

Usage:
    source /opt/ros/humble/setup.bash
    source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
    python3 ~/Dissertation/scripts/ekf_position_bridge.py
"""
import math
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from px4_msgs.msg import VehicleOdometry

DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

QOS_SUB = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5)

QOS_PUB = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1)


def safe_vec3(arr, default=0.0):
    """Return a list of 3 finite floats, replacing NaN/Inf with default."""
    out = []
    for v in arr:
        out.append(float(default) if (math.isnan(v) or math.isinf(v)) else float(v))
    return out[:3] + [float(default)] * max(0, 3 - len(out))


def safe_quat(arr):
    """Return a valid unit quaternion, falling back to identity [1,0,0,0]."""
    try:
        q = [float(v) for v in arr[:4]]
        if any(math.isnan(v) or math.isinf(v) for v in q):
            return [1.0, 0.0, 0.0, 0.0]
        norm = math.sqrt(sum(v*v for v in q))
        if norm < 1e-6:
            return [1.0, 0.0, 0.0, 0.0]
        return [v / norm for v in q]
    except Exception:
        return [1.0, 0.0, 0.0, 0.0]


class EKFBridge(Node):
    def __init__(self):
        super().__init__("ekf_position_bridge")
        self._latest = {d: None for d in DRONES}
        self._pubs   = {}
        self._count  = {d: 0 for d in DRONES}
        self._valid  = {d: False for d in DRONES}

        for drone in DRONES:
            self.create_subscription(
                VehicleOdometry,
                f"/{drone}/fmu/out/vehicle_odometry",
                lambda msg, d=drone: self._on_odom(d, msg),
                QOS_SUB)

            self._pubs[drone] = self.create_publisher(
                VehicleOdometry,
                f"/{drone}/fmu/in/vehicle_visual_odometry",
                QOS_PUB)

        self.create_timer(0.05, self._tick)  # 20 Hz
        self.get_logger().info(
            "[EKF-BRIDGE] Loopback: fmu/out/vehicle_odometry → "
            "fmu/in/vehicle_visual_odometry  (20 Hz, all 5 drones)")

    def _on_odom(self, drone, msg):
        self._latest[drone] = msg
        # Mark valid only when position contains finite values
        pos = list(msg.position)
        if len(pos) >= 3 and not any(math.isnan(v) or math.isinf(v) for v in pos[:3]):
            self._valid[drone] = True

    def _tick(self):
        now_us = int(self.get_clock().now().nanoseconds / 1000)

        for drone in DRONES:
            src = self._latest[drone]
            if src is None or not self._valid[drone]:
                continue

            msg = VehicleOdometry()
            msg.timestamp        = now_us
            msg.timestamp_sample = src.timestamp_sample
            msg.pose_frame       = VehicleOdometry.POSE_FRAME_NED

            msg.position = safe_vec3(src.position)
            msg.q        = safe_quat(src.q)

            msg.velocity_frame = VehicleOdometry.VELOCITY_FRAME_NED
            msg.velocity       = safe_vec3(src.velocity)

            msg.position_variance    = [0.01, 0.01, 0.01]
            msg.orientation_variance = [0.01, 0.01, 0.01]
            msg.velocity_variance    = [0.05, 0.05, 0.05]

            msg.reset_counter = int(src.reset_counter)
            msg.quality       = 100

            self._pubs[drone].publish(msg)
            self._count[drone] += 1

        # Status every 5s (100 ticks @ 20Hz)
        total = sum(self._count.values())
        if total > 0 and total % 100 == 0:
            active  = [d for d in DRONES if self._valid[d]]
            waiting = [d for d in DRONES if not self._valid[d]]
            self.get_logger().info(
                f"[EKF-BRIDGE] {total} msgs  active={active}"
                + (f"  waiting={waiting}" if waiting else ""))


def main():
    rclpy.init()
    node = EKFBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
