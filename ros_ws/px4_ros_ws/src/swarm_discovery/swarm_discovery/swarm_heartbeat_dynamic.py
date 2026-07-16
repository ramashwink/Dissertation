#!/usr/bin/env python3
"""
swarm_heartbeat_dynamic.py
==========================
Motion-experiment replacement for swarm_heartbeat.py.
Broadcasts LIVE ground truth position (from Gazebo via gz-transport)
instead of a fixed spawn coordinate.

Required for motion experiments — static heartbeats give wrong anchor
positions the moment drones move.

Run (one per drone):
    ros2 run swarm_discovery swarm_heartbeat_dynamic px4_1
    ros2 run swarm_discovery swarm_heartbeat_dynamic px4_2
    # etc.
"""
import sys
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from geometry_msgs.msg import PoseStamped
from swarm_msgs.msg import SwarmMember

HEARTBEAT_HZ = 5.0
DRONE_TYPE   = "gz_x500"
DRONE_NS     = sys.argv[1] if len(sys.argv) > 1 else "px4_1"

class DynamicHeartbeat(Node):
    def __init__(self):
        super().__init__(f"swarm_heartbeat_dynamic_{DRONE_NS}")
        self.pos           = [0.0, 0.0, 0.0]
        self.pos_received  = False

        self.create_subscription(
            PoseStamped,
            f"/sim/ground_truth/{DRONE_NS}/pose",
            self._on_gt, 10)

        self.pub = self.create_publisher(SwarmMember, "/swarm/heartbeat", 10)
        self.create_timer(1.0 / HEARTBEAT_HZ, self._tick)
        self.get_logger().info(
            f"[HB-DYN] {DRONE_NS} — waiting for ground truth, "
            f"broadcasting at {HEARTBEAT_HZ} Hz when ready")

    def _on_gt(self, msg):
        self.pos = [msg.pose.position.x,
                    msg.pose.position.y,
                    msg.pose.position.z]
        if not self.pos_received:
            self.pos_received = True
            self.get_logger().info(
                f"[HB-DYN] {DRONE_NS} first GT received: {[round(p,3) for p in self.pos]}")

    def _tick(self):
        if not self.pos_received:
            return
        m             = SwarmMember()
        m.header      = Header()
        m.header.stamp    = self.get_clock().now().to_msg()
        m.header.frame_id = "world"
        m.drone_ns    = DRONE_NS
        m.spawn_x     = float(self.pos[0])
        m.spawn_y     = float(self.pos[1])
        m.spawn_z     = float(self.pos[2])
        m.drone_type  = DRONE_TYPE
        m.is_armed    = True
        self.pub.publish(m)

def main():
    rclpy.init()
    node = DynamicHeartbeat()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
