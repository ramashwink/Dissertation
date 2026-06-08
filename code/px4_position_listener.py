#!/usr/bin/env python3
"""
Minimal PX4 position listener for the swarm testbed.

Subscribes to ONE drone's VehicleLocalPosition and prints pose + velocity.
This is the read-half baseline: confirms typed data decodes per-drone before
you write offboard-control and injection nodes.

Run (after `source /opt/ros/humble/setup.bash` and your workspace install):
    python3 px4_position_listener.py            # defaults to px4_3
    python3 px4_position_listener.py px4_1      # pick a different drone
"""
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    DurabilityPolicy,
    HistoryPolicy,
)

# PX4 v1.16+ uses message versioning, so the topic is vehicle_local_position_v1.
# Verify the message type with:
#     ros2 topic type /px4_3/fmu/out/vehicle_local_position_v1
# If it reports VehicleLocalPositionV1 instead, change this import + the type
# references below to match.
from px4_msgs.msg import VehicleLocalPosition


class PositionListener(Node):
    def __init__(self, drone_ns: str):
        super().__init__("px4_position_listener")

        # CRITICAL: PX4 publishes with BEST_EFFORT reliability. A subscriber
        # using ROS 2's default (RELIABLE) QoS receives NOTHING and silently
        # sits idle. This profile is mandatory for any PX4 /fmu/out topic.
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        topic = f"/{drone_ns}/fmu/out/vehicle_local_position_v1"
        self.sub = self.create_subscription(
            VehicleLocalPosition, topic, self.on_position, qos
        )
        self.get_logger().info(f"Listening to {topic}")

    def on_position(self, msg: VehicleLocalPosition):
        self.get_logger().info(
            f"pos x={msg.x:+.2f} y={msg.y:+.2f} z={msg.z:+.2f} | "
            f"vel vx={msg.vx:+.2f} vy={msg.vy:+.2f} vz={msg.vz:+.2f} | "
            f"hdg={msg.heading:+.2f} | xy_valid={msg.xy_valid} "
            f"dead_reckoning={msg.dead_reckoning}"
        )


def main():
    drone_ns = sys.argv[1] if len(sys.argv) > 1 else "px4_3"
    rclpy.init()
    node = PositionListener(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
