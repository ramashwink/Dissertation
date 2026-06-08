#!/usr/bin/env python3
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from swarm_msgs.msg import SwarmMember, SwarmRegistry as SwarmRegistryMsg

MEMBER_TIMEOUT_SEC = 10.0
REGISTRY_HZ        = 2.0
HEARTBEAT_HZ       = 2.0   # expected rate — suspects publish >3x this

class SwarmRegistryNode(Node):
    def __init__(self):
        super().__init__("swarm_registry")
        self._members    = {}   # ns -> {member, last_seen, first_seen, heartbeat_count}
        self._total_seen = set()
        self.create_subscription(SwarmMember, "/swarm/heartbeat", self._on_heartbeat, 10)
        self.pub = self.create_publisher(SwarmRegistryMsg, "/swarm/registry", 10)
        self.create_timer(1.0 / REGISTRY_HZ, self._publish_registry)
        self.get_logger().info(f"[REGISTRY] Listening on /swarm/heartbeat | timeout={MEMBER_TIMEOUT_SEC}s")

    def _on_heartbeat(self, msg):
        ns  = msg.drone_ns
        now = time.monotonic()
        if ns not in self._members:
            self.get_logger().info(f"[REGISTRY] New member: {ns} @ ({msg.spawn_x:.2f},{msg.spawn_y:.2f},{msg.spawn_z:.2f})")
        self._members[ns] = {
            "member":          msg,
            "last_seen":       now,
            "first_seen":      self._members.get(ns, {}).get("first_seen", now),
            "heartbeat_count": self._members.get(ns, {}).get("heartbeat_count", 0) + 1,
        }
        self._total_seen.add(ns)

    def _publish_registry(self):
        now     = time.monotonic()
        expired = [ns for ns, v in self._members.items()
                   if now - v["last_seen"] > MEMBER_TIMEOUT_SEC]
        for ns in expired:
            self.get_logger().warn(f"[REGISTRY] Member expired: {ns}")
            del self._members[ns]

        # Sybil heuristic: observed rate > 3x expected HEARTBEAT_HZ
        sybil_suspects = 0
        for ns, v in self._members.items():
            elapsed = max(now - v["first_seen"], 1.0)
            rate    = v["heartbeat_count"] / elapsed
            if rate > HEARTBEAT_HZ * 3:
                sybil_suspects += 1
                self.get_logger().warn(f"[REGISTRY] Sybil suspect: {ns} rate={rate:.1f} Hz")

        reg                     = SwarmRegistryMsg()
        reg.header              = Header()
        reg.header.stamp        = self.get_clock().now().to_msg()
        reg.header.frame_id     = "world"
        reg.members             = [v["member"] for v in
                                   sorted(self._members.values(),
                                          key=lambda x: x["member"].drone_ns)]
        reg.total_seen          = len(self._total_seen)
        reg.sybil_suspect_count = sybil_suspects
        self.pub.publish(reg)

        if int(now) % 5 == 0:
            self.get_logger().info(
                f"[REGISTRY] Live: {[m.drone_ns for m in reg.members]} | "
                f"total_seen={reg.total_seen} | sybil_suspects={sybil_suspects}"
            )

def main():
    rclpy.init()
    node = SwarmRegistryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
