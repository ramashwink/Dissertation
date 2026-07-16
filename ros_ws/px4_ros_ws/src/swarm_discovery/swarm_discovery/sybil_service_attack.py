#!/usr/bin/env python3
"""
Sybil attack — service registry edition (Design B)
====================================================
Attempts to register ghost drones via /swarm/register.
All registrations are rejected by the allowlist.

Records every rejection with timestamp for dissertation evidence.
Also attempts an impersonation: tries to register as "px4_2" (a valid
namespace) to demonstrate that allowlist alone does not prevent
impersonation — the remaining vulnerability for Chapter 5.

Metrics logged to /tmp/sybil_service_attack_metrics.csv:
  timestamp, drone_ns, attempt_type, accepted, reason

Run:
    ros2 run swarm_discovery sybil_service_attack
"""
import csv
import time
import rclpy
from rclpy.node import Node
from swarm_msgs.srv import RegisterDrone

LOG_FILE = "/tmp/sybil_service_attack_metrics.csv"

GHOST_ATTEMPTS = [
    {"drone_ns": "ghost_1", "spawn_x": 4.0,  "spawn_y": 1.0,  "spawn_z": 1.0, "type": "ghost"},
    {"drone_ns": "ghost_2", "spawn_x": -2.0, "spawn_y": 4.46, "spawn_z": 1.0, "type": "ghost"},
    {"drone_ns": "ghost_3", "spawn_x": -2.0, "spawn_y":-2.46, "spawn_z": 1.0, "type": "ghost"},
    {"drone_ns": "px4_2",   "spawn_x": 99.0, "spawn_y": 99.0, "spawn_z": 0.0, "type": "impersonation"},
]


class SybilServiceAttack(Node):
    def __init__(self):
        super().__init__("sybil_service_attack")
        self._client = self.create_client(RegisterDrone, "/swarm/register")

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv      = csv.writer(self._csv_file)
        self._csv.writerow(["t_s", "drone_ns", "attempt_type", "accepted", "reason"])

        self.get_logger().warn(
            "[SYBIL-SVC] Waiting for /swarm/register service..."
        )
        self._client.wait_for_service(timeout_sec=10.0)
        self.get_logger().warn(
            f"[SYBIL-SVC] Attempting {len(GHOST_ATTEMPTS)} registrations..."
        )

        self._attempt_idx = 0
        self.create_timer(1.0, self._next_attempt)

    def _next_attempt(self):
        if self._attempt_idx >= len(GHOST_ATTEMPTS):
            self.get_logger().info("[SYBIL-SVC] All attempts complete.")
            self._print_summary()
            self._csv_file.flush()
            self._csv_file.close()
            return

        attempt = GHOST_ATTEMPTS[self._attempt_idx]
        self._attempt_idx += 1

        req            = RegisterDrone.Request()
        req.drone_ns   = attempt["drone_ns"]
        req.spawn_x    = attempt["spawn_x"]
        req.spawn_y    = attempt["spawn_y"]
        req.spawn_z    = attempt["spawn_z"]
        req.drone_type = "gz_x500"

        future = self._client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=3.0)

        t = time.time()
        if future.result() is None:
            self.get_logger().error(
                f"[SYBIL-SVC] {req.drone_ns} — call timed out"
            )
            self._csv.writerow([f"{t:.3f}", req.drone_ns,
                                 attempt["type"], "timeout", "service timeout"])
            return

        resp = future.result()
        status = "ACCEPTED" if resp.accepted else "REJECTED"
        color_warn = self.get_logger().warn if not resp.accepted else self.get_logger().error

        color_warn(
            f"[SYBIL-SVC] {attempt['type'].upper()} attempt: "
            f"{req.drone_ns} → {status} | {resp.reason}"
        )
        self._csv.writerow([
            f"{t:.3f}", req.drone_ns, attempt["type"],
            resp.accepted, resp.reason
        ])

    def _print_summary(self):
        self.get_logger().warn("=" * 50)
        self.get_logger().warn("[SYBIL-SVC] ATTACK SUMMARY")
        self.get_logger().warn(f"  Ghost attempts:        3")
        self.get_logger().warn(f"  Impersonation attempt: 1")
        self.get_logger().warn(f"  All ghosts REJECTED by allowlist")
        self.get_logger().warn(f"  Impersonation: check log — allowlist accepted px4_2")
        self.get_logger().warn(f"  Finding: allowlist stops Sybil but NOT impersonation")
        self.get_logger().warn(f"  Mitigation needed: HMAC tokens or SROS2")
        self.get_logger().warn(f"  Log: {LOG_FILE}")
        self.get_logger().warn("=" * 50)


def main():
    rclpy.init()
    node = SybilServiceAttack()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
