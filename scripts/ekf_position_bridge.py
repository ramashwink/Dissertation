#!/usr/bin/env python3
"""
ekf_position_bridge.py
======================
Bridges Gazebo ground truth → PX4 EKF2 via ROS 2 vehicle_visual_odometry.
Keeps EKF2 position-valid during motion experiments.

Run in a dedicated terminal after arming. Leave running during experiment.
Ctrl-C when done.

Usage:
    source /opt/ros/humble/setup.bash
    source ~/Dissertation/ros_ws/px4_ros_ws/install/setup.bash
    python3 ~/Dissertation/scripts/ekf_position_bridge.py
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from geometry_msgs.msg import PoseStamped
from px4_msgs.msg import VehicleOdometry

DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

QOS_PX4 = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST, depth=1)

class EKFBridge(Node):
    def __init__(self):
        super().__init__("ekf_position_bridge")
        self.pos = {d: None for d in DRONES}
        self.pubs = {}
        self.count = {d: 0 for d in DRONES}

        for drone in DRONES:
            # Subscribe to Gazebo ground truth
            self.create_subscription(
                PoseStamped,
                f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self._on_gt(d, msg), 10)

            # Publish to PX4 EKF2 via ROS 2
            self.pubs[drone] = self.create_publisher(
                VehicleOdometry,
                f"/{drone}/fmu/in/vehicle_visual_odometry",
                QOS_PX4)

        self.create_timer(0.05, self._tick)   # 20 Hz
        self.get_logger().info(
            "[EKF-BRIDGE] Bridging Gazebo GT → PX4 EKF2 for all 5 drones at 20 Hz")

    def _on_gt(self, drone, msg):
        self.pos[drone] = msg

    def _tick(self):
        now_us = int(self.get_clock().now().nanoseconds / 1000)
        for drone in DRONES:
            p = self.pos[drone]
            if p is None:
                continue
            msg = VehicleOdometry()
            msg.timestamp        = now_us
            msg.timestamp_sample = now_us
            msg.pose_frame = VehicleOdometry.POSE_FRAME_NED
            # Convert ENU (Gazebo) → NED (PX4): x=y_enu, y=x_enu, z=-z_enu
            msg.position = [
                float(p.pose.position.y),
                float(p.pose.position.x),
                float(-p.pose.position.z)]
            msg.q = [1.0, 0.0, 0.0, 0.0]
            msg.velocity_frame = VehicleOdometry.VELOCITY_FRAME_NED
            msg.velocity = [0.0, 0.0, 0.0]
            msg.position_variance    = [0.01, 0.01, 0.01]
            msg.orientation_variance = [0.01, 0.01, 0.01]
            msg.velocity_variance    = [0.1,  0.1,  0.1]
            msg.reset_counter = 0
            msg.quality = 100
            self.pubs[drone].publish(msg)
            self.count[drone] += 1

        # Log every 5s
        total = sum(self.count.values())
        if total % 500 == 0 and total > 0:
            self.get_logger().info(
                f"[EKF-BRIDGE] Published {total} odometry msgs — "
                f"EKF2 position maintained")

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
