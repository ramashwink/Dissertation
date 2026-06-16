#!/usr/bin/env python3
"""
Byzantine Insider Attack  (Enhancement 4)
==========================================
Models a *legitimately registered, initially honest* drone that becomes
compromised mid-flight and starts injecting a gradually increasing position
bias into its self_estimate publications.

Unlike Sybil (fake identities) or Wormhole (range manipulation), a Byzantine
insider is indistinguishable from a well-behaved drone by any identity-layer
check.  It passes allowlist verification, heartbeat rate heuristics, and
chi2 gating in early phases — the bias only grows to detectable levels after
the EKF has already absorbed the corrupt measurements into its state.

Attack phases:
  0 – WARMUP     (0–10s):  drone behaves honestly, building trust
  1 – RAMP       (10–40s): bias grows linearly from 0 → BIAS_MAX metres
                            innovations grow slowly, evading chi2 threshold
  2 – SUSTAINED  (40–90s): bias held at BIAS_MAX — estimate fully corrupted

Bias direction: configurable; default is +X/+Y axis (causes estimated
position to drift, corrupting swarm topology for cooperative tasks).

Evil drone: px4_2 (standard evil-drone convention across this attack suite)
Honest drones: px4_1, px4_3, px4_4, px4_5

Affected mitigations:
  WLS + Huber:      bias below HUBER_DELTA is not down-weighted
  WLS + Tukey:      bias below TUKEY_C is not zeroed
  EKF + chi2:       if bias ramp < sqrt(CHI2_THRESHOLD / trace(S_inv)),
                    innovations stay below gate → bias gets accepted
  RANSAC:           if BIAS_MAX < INLIER_THRESHOLD, the drone is always
                    counted as an inlier → no outlier rejection

Run:
    ros2 run swarm_discovery byzantine_insider_attack
    ros2 run swarm_discovery byzantine_insider_attack px4_2 0.8  # drone, bias(m)

Smoke test (short run, for parameter tuning):
    SMOKE_ATTACK_SEC=20 SMOKE_WARMUP_SEC=3 SMOKE_RAMP_SEC=10 \\
        ros2 run swarm_discovery byzantine_insider_attack px4_2 0.8

STRIDE: Tampering, Elevation of Privilege

PATCH NOTES (validation pass):
  - Added _true_pos_received gate + throttled warning. Previously,
    self._true_pos was seeded from SPAWN_POSITIONS and only updated via
    _on_true_estimate; if the compromised drone's real coop_loc_* node was
    not yet publishing self_estimate when the ramp/sustained phase began,
    the "bias" was applied to a frozen spawn point rather than a live,
    moving estimate -- silently changing the attack from "drift on a live
    estimate" to "static fake position."
  - Logs true_pos_received per tick so validate_attacks.py can confirm the
    bias was applied against a live estimate for the bulk of the run.
  - Default compromised drone changed px4_3 -> px4_2 to match the
    standardised evil-drone convention used across the attack suite.
  - ATTACK_SEC / WARMUP_SEC / RAMP_SEC overridable via env vars for smoke
    testing.
"""
import os, sys, csv, time
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PointStamped

# Default compromised drone (must be a real, registered drone)
# CHANGED: px4_3 -> px4_2 to match the standardised evil-drone convention.
BYZANTINE_DRONE = "px4_2"
ALL_DRONES      = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
HONEST_DRONES   = [d for d in ALL_DRONES if d != BYZANTINE_DRONE]

BIAS_MAX        = 0.8    # metres — max position bias injected
BIAS_AXIS       = np.array([1.0, 0.5, 0.0])  # bias direction (normalised below)
WARMUP_SEC      = float(os.environ.get("SMOKE_WARMUP_SEC", 10.0))
RAMP_SEC        = float(os.environ.get("SMOKE_RAMP_SEC", 30.0))   # ramp duration after warmup
ATTACK_SEC      = float(os.environ.get("SMOKE_ATTACK_SEC", 90.0))
PUBLISH_HZ      = 10.0
LOG_FILE        = "/tmp/byzantine_insider_attack_metrics.csv"

SPAWN_POSITIONS = {
    "px4_1": np.array([0.0, 0.0, 0.0]),
    "px4_2": np.array([2.0, 0.0, 0.0]),
    "px4_3": np.array([4.0, 0.0, 0.0]),
    "px4_4": np.array([2.0, 2.0, 0.0]),
    "px4_5": np.array([4.0, 2.0, 0.0]),
}

_BIAS_DIR = BIAS_AXIS / np.linalg.norm(BIAS_AXIS)


class ByzantineInsiderAttack(Node):
    def __init__(self, compromised_ns, bias_max):
        super().__init__("byzantine_insider_attack")
        self.compromised_ns = compromised_ns
        self.bias_max       = bias_max
        self.start_time     = time.monotonic()

        self.est            = {d: None for d in ALL_DRONES}
        self.gt             = {d: None for d in ALL_DRONES}
        self._true_pos      = SPAWN_POSITIONS[compromised_ns].copy()
        self._true_pos_received = False

        # Subscribe to the compromised drone's real self_estimate (to add bias on top)
        self.create_subscription(
            PoseStamped, f"/{compromised_ns}/coop/self_estimate",
            self._on_true_estimate, 10)

        # Biased self_estimate publisher — overwrites the honest one
        self._biased_pub = self.create_publisher(
            PoseStamped, f"/{compromised_ns}/coop/self_estimate", 10)

        for drone in ALL_DRONES:
            self.create_subscription(
                PoseStamped, f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self.gt.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y,
                    msg.pose.position.z])}), 10)
            self.create_subscription(
                PoseStamped, f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self.est.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y,
                    msg.pose.position.z])}), 10)

        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        header = ["t_s", "phase", "bias_m", "bias_x", "bias_y", "bias_z",
                  "true_pos_received"]
        for d in ALL_DRONES:
            header += [f"{d}_est_x", f"{d}_est_y", f"{d}_est_z",
                       f"{d}_gt_x",  f"{d}_gt_y",  f"{d}_gt_z",
                       f"{d}_error_m",
                       f"{d}_is_compromised"]
        self._csv.writerow(header)

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.get_logger().warn(
            f"[BYZANTINE] Compromised drone: {compromised_ns} | "
            f"max_bias={bias_max}m direction={_BIAS_DIR.round(3)} | "
            f"ramp={WARMUP_SEC:.0f}-{WARMUP_SEC+RAMP_SEC:.0f}s | "
            f"attack_window={ATTACK_SEC:.0f}s")

    def _on_true_estimate(self, msg):
        self._true_pos = np.array([
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])
        if not self._true_pos_received:
            self._true_pos_received = True
            self.get_logger().info(
                f"[BYZANTINE] First {self.compromised_ns} true self_estimate "
                f"received: {self._true_pos.round(3)} -- bias injection now "
                f"applies to a live estimate, not frozen spawn")

    def _current_bias(self, elapsed):
        if elapsed < WARMUP_SEC:
            return 0.0
        ramp_progress = min((elapsed - WARMUP_SEC) / RAMP_SEC, 1.0)
        return self.bias_max * ramp_progress

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        if elapsed > ATTACK_SEC:
            self.get_logger().info("[BYZANTINE] Complete.")
            self._csv_file.flush(); self._csv_file.close()
            self.destroy_node(); return

        bias_mag = self._current_bias(elapsed)
        bias_vec = _BIAS_DIR * bias_mag

        if elapsed < WARMUP_SEC:
            phase = "warmup"
        elif elapsed < WARMUP_SEC + RAMP_SEC:
            phase = "ramp"
        else:
            phase = "sustained"

        # ADDED: throttled warning if bias is ramping but we've never heard a
        # real self_estimate -- means we're biasing a frozen spawn point, not
        # "a drone whose live estimate drifts."
        if phase != "warmup" and not self._true_pos_received:
            self.get_logger().warn(
                f"[BYZANTINE] t={elapsed:.1f}s phase={phase} but no "
                f"{self.compromised_ns} self_estimate received yet -- "
                f"injecting bias against frozen SPAWN_POSITIONS, not live state. "
                f"Check coop_loc_* for {self.compromised_ns} is running.",
                throttle_duration_sec=5.0
            )

        # Publish biased estimate for the compromised drone
        biased_pos = self._true_pos + bias_vec
        msg = PoseStamped()
        msg.header.stamp       = self.get_clock().now().to_msg()
        msg.header.frame_id    = "world"
        msg.pose.position.x    = float(biased_pos[0])
        msg.pose.position.y    = float(biased_pos[1])
        msg.pose.position.z    = float(biased_pos[2])
        msg.pose.orientation.w = 1.0
        self._biased_pub.publish(msg)

        row = [f"{elapsed:.3f}", phase, f"{bias_mag:.4f}",
               f"{bias_vec[0]:.4f}", f"{bias_vec[1]:.4f}", f"{bias_vec[2]:.4f}",
               int(self._true_pos_received)]
        for drone in ALL_DRONES:
            is_comp = 1 if drone == self.compromised_ns else 0
            est, gt = self.est.get(drone), self.gt.get(drone)
            if est is not None and gt is not None:
                err = float(np.linalg.norm(est - gt))
                row += [f"{est[0]:.4f}", f"{est[1]:.4f}", f"{est[2]:.4f}",
                        f"{gt[0]:.4f}",  f"{gt[1]:.4f}",  f"{gt[2]:.4f}",
                        f"{err:.4f}", is_comp]
            else:
                row += ["", "", "", "", "", "", "", is_comp]
        self._csv.writerow(row)

        if int(elapsed) % 10 == 0 and int(elapsed * PUBLISH_HZ) % int(PUBLISH_HZ) == 0:
            parts = []
            for d in ALL_DRONES:
                e, g = self.est.get(d), self.gt.get(d)
                if e is not None and g is not None:
                    tag = " [COMP]" if d == self.compromised_ns else ""
                    parts.append(f"{d}={np.linalg.norm(e-g):.3f}m{tag}")
            self.get_logger().warn(
                f"[BYZANTINE t={elapsed:.0f}s phase={phase}] "
                f"bias={bias_mag:.3f}m | {' | '.join(parts)}")


def main():
    compromised_ns = sys.argv[1] if len(sys.argv) > 1 else BYZANTINE_DRONE
    bias_max       = float(sys.argv[2]) if len(sys.argv) > 2 else BIAS_MAX
    rclpy.init()
    node = ByzantineInsiderAttack(compromised_ns, bias_max)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

if __name__ == "__main__":
    main()
