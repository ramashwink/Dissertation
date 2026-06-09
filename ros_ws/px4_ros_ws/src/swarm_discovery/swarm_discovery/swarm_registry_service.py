#!/usr/bin/env python3
"""
Swarm registry — service-based (Design B)
==========================================
Replaces swarm_registry.py. Exposes two ROS 2 services:
  /swarm/register   (RegisterDrone) — drone calls once on startup
  /swarm/keepalive  (Keepalive)     — drone calls every KEEPALIVE_SEC

Validates registrations against an allowlist.
Publishes /swarm/registry at REGISTRY_HZ (same topic/message as Design A
so all downstream nodes — coop_loc_dynamic, swarm_viz — are unchanged).

SECURITY NOTE (dissertation):
  Design A accepted all heartbeats unconditionally.
  Design B rejects any drone_ns not in ALLOWED_NAMESPACES.
  Sybil attack calls RegisterDrone("ghost_1"...) → accepted=False.
  The ghost never enters the member list → WLS solver is not poisoned.

  Remaining vulnerability: the allowlist is a shared secret embedded in
  the registry node. An attacker who knows the allowed namespaces can
  still spoof them (impersonation attack). Full mitigation requires
  HMAC tokens or DDS Security (SROS2) — see dissertation Chapter 5.

Metrics logged to /tmp/registry_service_metrics.csv:
  timestamp, drone_ns, accepted, reason, total_members, rejected_count
"""
import time
import csv
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from swarm_msgs.msg import SwarmMember, SwarmRegistry as SwarmRegistryMsg
from swarm_msgs.srv import RegisterDrone, Keepalive

ALLOWED_NAMESPACES = {"px4_1", "px4_2", "px4_3"}
KEEPALIVE_TIMEOUT  = 15.0   # drop member if no keepalive for this long
REGISTRY_HZ        = 2.0
LOG_FILE           = "/tmp/registry_service_metrics.csv"


class SwarmRegistryService(Node):
    def __init__(self):
        super().__init__("swarm_registry_service")

        self._members       = {}   # ns -> {member, last_keepalive, registered_at}
        self._total_seen    = set()
        self._rejected      = []   # list of (timestamp, drone_ns, reason)

        self._register_srv  = self.create_service(
            RegisterDrone, "/swarm/register", self._on_register)
        self._keepalive_srv = self.create_service(
            Keepalive, "/swarm/keepalive", self._on_keepalive)

        self._pub = self.create_publisher(
            SwarmRegistryMsg, "/swarm/registry", 10)
        self.create_timer(1.0 / REGISTRY_HZ, self._publish_registry)

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow([
            "t_s", "drone_ns", "accepted", "reason",
            "total_members", "rejected_count"
        ])

        self.get_logger().info(
            f"[REGISTRY-SVC] Services ready\n"
            f"  /swarm/register  (RegisterDrone)\n"
            f"  /swarm/keepalive (Keepalive)\n"
            f"  Allowlist: {sorted(ALLOWED_NAMESPACES)}\n"
            f"  Logging to {LOG_FILE}"
        )

    def _on_register(self, request, response):
        ns  = request.drone_ns
        now = time.monotonic()
        t   = time.time()

        if ns not in ALLOWED_NAMESPACES:
            response.accepted = False
            response.reason   = f"REJECTED: '{ns}' not in allowlist"
            self._rejected.append((t, ns, response.reason))
            self.get_logger().warn(
                f"[REGISTRY-SVC] {response.reason}"
            )
            self._log_row(t, ns, False, response.reason)
            return response

        if ns in self._members:
            response.accepted = True
            response.reason   = "already registered — refreshed"
        else:
            response.accepted = True
            response.reason   = "registered"
            self.get_logger().info(
                f"[REGISTRY-SVC] Registered: {ns} @ "
                f"({request.spawn_x:.2f},{request.spawn_y:.2f},{request.spawn_z:.2f})"
            )

        member = SwarmMember()
        member.header           = Header()
        member.header.stamp     = self.get_clock().now().to_msg()
        member.header.frame_id  = "world"
        member.drone_ns         = ns
        member.spawn_x          = request.spawn_x
        member.spawn_y          = request.spawn_y
        member.spawn_z          = request.spawn_z
        member.drone_type       = request.drone_type
        member.is_armed         = False

        self._members[ns] = {
            "member":        member,
            "last_keepalive": now,
            "registered_at": now,
        }
        self._total_seen.add(ns)
        self._log_row(t, ns, True, response.reason)
        return response

    def _on_keepalive(self, request, response):
        ns = request.drone_ns
        if ns in self._members:
            self._members[ns]["last_keepalive"] = time.monotonic()
            response.acknowledged = True
        else:
            response.acknowledged = False
            self.get_logger().warn(
                f"[REGISTRY-SVC] Keepalive from unregistered drone: {ns}"
            )
        return response

    def _publish_registry(self):
        now     = time.monotonic()
        expired = [
            ns for ns, v in self._members.items()
            if now - v["last_keepalive"] > KEEPALIVE_TIMEOUT
        ]
        for ns in expired:
            self.get_logger().warn(f"[REGISTRY-SVC] Expired: {ns}")
            del self._members[ns]

        reg                     = SwarmRegistryMsg()
        reg.header              = Header()
        reg.header.stamp        = self.get_clock().now().to_msg()
        reg.header.frame_id     = "world"
        reg.members             = [
            v["member"] for v in
            sorted(self._members.values(),
                   key=lambda x: x["member"].drone_ns)
        ]
        reg.total_seen          = len(self._total_seen)
        reg.sybil_suspect_count = len(self._rejected)
        self._pub.publish(reg)

        if int(now) % 5 == 0:
            self.get_logger().info(
                f"[REGISTRY-SVC] Live: {[m.drone_ns for m in reg.members]} | "
                f"rejected_total={len(self._rejected)}"
            )

    def _log_row(self, t, ns, accepted, reason):
        self._csv.writerow([
            f"{t:.3f}", ns, accepted, reason,
            len(self._members), len(self._rejected)
        ])
        self._csv_file.flush()


def main():
    rclpy.init()
    node = SwarmRegistryService()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
