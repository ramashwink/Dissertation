#!/usr/bin/env python3
"""
Swarm client — service-based (Design B)
========================================
Replaces swarm_heartbeat.py. Calls /swarm/register once on startup,
then sends /swarm/keepalive every KEEPALIVE_SEC to stay registered.

If the registry rejects the registration (not in allowlist), the node
logs the rejection and exits — it will not retry with a fake identity.

Run (one per drone):
    ros2 run swarm_discovery swarm_client px4_1 0.0 0.0 0.0
    ros2 run swarm_discovery swarm_client px4_2 0.0 1.0 0.0
    ros2 run swarm_discovery swarm_client px4_3 0.0 2.0 0.0
"""
import sys
import rclpy
from rclpy.node import Node
from swarm_msgs.srv import RegisterDrone, Keepalive

KEEPALIVE_SEC = 3.0
DRONE_TYPE    = "gz_x500"


class SwarmClient(Node):
    def __init__(self, ns, spawn):
        super().__init__("swarm_client")
        self.ns    = ns
        self.spawn = spawn
        self._registered = False

        self._reg_client  = self.create_client(RegisterDrone, "/swarm/register")
        self._kp_client   = self.create_client(Keepalive,     "/swarm/keepalive")

        self.get_logger().info(f"[CLIENT] {ns} waiting for /swarm/register service...")
        self._reg_client.wait_for_service(timeout_sec=10.0)
        self._register()

        self.create_timer(KEEPALIVE_SEC, self._send_keepalive)

    def _register(self):
        req           = RegisterDrone.Request()
        req.drone_ns  = self.ns
        req.spawn_x   = float(self.spawn[0])
        req.spawn_y   = float(self.spawn[1])
        req.spawn_z   = float(self.spawn[2])
        req.drone_type = DRONE_TYPE

        future = self._reg_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)

        if future.result() is None:
            self.get_logger().error("[CLIENT] Registration call timed out")
            return

        resp = future.result()
        if resp.accepted:
            self._registered = True
            self.get_logger().info(
                f"[CLIENT] {self.ns} registered — {resp.reason}"
            )
        else:
            self.get_logger().error(
                f"[CLIENT] {self.ns} REJECTED — {resp.reason}"
            )

    def _send_keepalive(self):
        if not self._registered:
            return
        if not self._kp_client.wait_for_service(timeout_sec=1.0):
            return
        req          = Keepalive.Request()
        req.drone_ns = self.ns
        self._kp_client.call_async(req)


def main():
    if len(sys.argv) < 2:
        print("Usage: swarm_client.py <namespace> [spawn_x] [spawn_y] [spawn_z]")
        sys.exit(1)
    ns      = sys.argv[1]
    spawn_x = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    spawn_y = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    spawn_z = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    rclpy.init()
    node = SwarmClient(ns, (spawn_x, spawn_y, spawn_z))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
