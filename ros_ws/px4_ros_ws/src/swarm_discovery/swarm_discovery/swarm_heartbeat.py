#!/usr/bin/env python3
import sys
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from swarm_msgs.msg import SwarmMember

HEARTBEAT_HZ = 2.0
DRONE_TYPE   = "gz_x500"

class SwarmHeartbeat(Node):
    def __init__(self, namespace, spawn):
        super().__init__("swarm_heartbeat")
        self.ns    = namespace
        self.spawn = spawn
        self.pub   = self.create_publisher(SwarmMember, "/swarm/heartbeat", 10)
        self.create_timer(1.0 / HEARTBEAT_HZ, self._tick)
        self.get_logger().info(f"[HEARTBEAT] {namespace} @ spawn={spawn} advertising at {HEARTBEAT_HZ} Hz")

    def _tick(self):
        msg             = SwarmMember()
        msg.header      = Header()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.drone_ns = self.ns
        msg.spawn_x     = float(self.spawn[0])
        msg.spawn_y     = float(self.spawn[1])
        msg.spawn_z     = float(self.spawn[2])
        msg.drone_type  = DRONE_TYPE
        msg.is_armed    = False
        self.pub.publish(msg)

def main():
    if len(sys.argv) < 2:
        print("Usage: swarm_heartbeat.py <namespace> [spawn_x] [spawn_y] [spawn_z]")
        sys.exit(1)
    ns      = sys.argv[1]
    spawn_x = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    spawn_y = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    spawn_z = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    rclpy.init()
    node = SwarmHeartbeat(ns, (spawn_x, spawn_y, spawn_z))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
