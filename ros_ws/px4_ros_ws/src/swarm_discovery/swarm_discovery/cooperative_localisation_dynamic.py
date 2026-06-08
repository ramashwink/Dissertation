#!/usr/bin/env python3
import sys
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped, PoseStamped
from scipy.optimize import least_squares
from swarm_msgs.msg import SwarmRegistry, SwarmMember

PUBLISH_HZ = 10.0

class DynamicCooperativeLocalisation(Node):
    def __init__(self, drone_ns):
        super().__init__("cooperative_localisation_dynamic")
        self.ns                  = drone_ns
        self._known_members      = {}   # namespace -> spawn np.array
        self._range_subs         = {}
        self._est_subs           = {}
        self._latest_range_vec   = {}
        self._latest_neighbour_pos = {}
        self._estimate           = np.array([0.0, 0.0, 0.0])
        self._own_spawn_known    = False
        self._iteration          = 0

        self.create_subscription(SwarmRegistry, "/swarm/registry", self._on_registry, 10)
        self._self_est_pub = self.create_publisher(PoseStamped, f"/{drone_ns}/coop/self_estimate", 10)
        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().info(f"[COOP-DYN] {drone_ns} waiting for /swarm/registry")

    def _on_registry(self, msg):
        incoming = {m.drone_ns: m for m in msg.members}
        if msg.sybil_suspect_count > 0:
            self.get_logger().warn(f"[COOP-DYN] Registry reports {msg.sybil_suspect_count} Sybil suspect(s)")

        for ns, member in incoming.items():
            if ns == self.ns:
                if not self._own_spawn_known:
                    self._estimate        = np.array([member.spawn_x, member.spawn_y, member.spawn_z])
                    self._own_spawn_known = True
                    self.get_logger().info(f"[COOP-DYN] Own spawn from registry: {self._estimate}")
                continue
            if ns not in self._known_members:
                self._add_neighbour(ns, member)

        for ns in [ns for ns in self._known_members if ns not in incoming]:
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

        self.get_logger().info(f"[COOP-DYN] Added neighbour: {ns} (total: {len(self._known_members)})")

    def _remove_neighbour(self, ns):
        del self._known_members[ns]
        self._latest_range_vec.pop(ns, None)
        self._latest_neighbour_pos.pop(ns, None)
        for d, topic in [(self._range_subs, f"/{self.ns}/coop/range_to/{ns}"),
                         (self._est_subs,   f"/{ns}/coop/self_estimate")]:
            if topic in d:
                self.destroy_subscription(d.pop(topic))
        self.get_logger().warn(f"[COOP-DYN] Removed neighbour: {ns}")

    def _on_range(self, neighbour, msg):
        self._latest_range_vec[neighbour] = np.array([msg.point.x, msg.point.y, msg.point.z])

    def _on_neighbour_est(self, neighbour, msg):
        self._latest_neighbour_pos[neighbour] = np.array([msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])

    def _tick(self):
        if not self._known_members:
            if self._iteration % 20 == 0:
                self.get_logger().warn("[COOP-DYN] No neighbours yet — waiting for registry")
            self._iteration += 1
            return

        ready = [ns for ns in self._known_members if self._latest_range_vec.get(ns) is not None]
        if ready:
            new_est = self._solve_wls(ready)
            if new_est is not None:
                self._estimate = new_est

        self._publish_self_estimate()
        self._iteration += 1

    def _solve_wls(self, active):
        positions     = np.array([self._latest_neighbour_pos[n] for n in active])
        observed_vecs = np.array([self._latest_range_vec[n]     for n in active])

        def residuals(p):
            return (positions - p[np.newaxis, :] - observed_vecs).flatten()

        try:
            result = least_squares(residuals, self._estimate, method="lm")
            return result.x if result.success else None
        except Exception as e:
            self.get_logger().error(f"WLS failed: {e}")
            return None

    def _publish_self_estimate(self):
        msg = PoseStamped()
        msg.header.stamp       = self.get_clock().now().to_msg()
        msg.header.frame_id    = "world"
        msg.pose.position.x    = float(self._estimate[0])
        msg.pose.position.y    = float(self._estimate[1])
        msg.pose.position.z    = float(self._estimate[2])
        msg.pose.orientation.w = 1.0
        self._self_est_pub.publish(msg)

def main():
    ns = sys.argv[1] if len(sys.argv) > 1 else "px4_3"
    rclpy.init()
    node = DynamicCooperativeLocalisation(ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
