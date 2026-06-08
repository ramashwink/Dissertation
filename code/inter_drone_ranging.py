#!/usr/bin/env python3
"""
Inter-drone ranging publisher -- step 2 of the cooperative-localisation stack.

Subscribes to the per-drone ground-truth pose topics produced by step 1
(ground_truth_demux), and for every ordered pair (observer, observed)
publishes a noisy LiDAR-style relative-position measurement.

Output topics, one per ordered pair:
    /px4_N/coop/range_to/px4_M   (geometry_msgs/PointStamped)

`point.{x,y,z}` is the noised relative-position vector from observer N to
observed neighbour M, expressed in the world frame.

Noise model (LiDAR-style):
    - Range:   Gaussian, sigma = RANGE_SIGMA metres
    - Bearing: small-angle perpendicular perturbation,
               sigma ~ BEARING_SIGMA radians
    - Independent noise per (observer, observed) direction, every cycle

KEY FIX (v2): Per-pair publishing replaces the old monolithic gate.
The old code blocked ALL pairs if ANY single drone's ground-truth was
stale. Now each (observer, observed) pair publishes independently,
skipping only the specific pair that lacks fresh data. A staleness
timeout (STALE_SEC) prevents publishing with arbitrarily old poses.

Run (after step 1 / ground_truth_demux is publishing):
    python3 inter_drone_ranging.py

Make sure only ONE instance is running. If you see topic names like
/px4_3/coop/range_to/px4_2_2, a duplicate node is running -- kill all
instances with:  pkill -f inter_drone_ranging.py
"""
import time
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PointStamped


# ----- Configuration -----
DRONES = ["px4_1", "px4_2", "px4_3"]

RANGE_SIGMA   = 0.05      # metres  (5 cm; typical short-range LiDAR)
BEARING_SIGMA = 0.0087    # radians (~0.5 degrees)

PUBLISH_HZ = 25.0         # downsampled from the 50 Hz ground-truth feed

# A ground-truth pose older than this is considered stale; skip that pair
# rather than publishing with ancient data. 0.5 s = 12.5 missed GT frames.
STALE_SEC = 0.5


class InterDroneRanging(Node):
    def __init__(self):
        super().__init__("inter_drone_ranging")

        self._rng = np.random.default_rng(seed=None)

        # Latest known true position per drone + the wall-clock time it arrived.
        self._latest      = {d: None for d in DRONES}
        self._latest_time = {d: None for d in DRONES}

        for drone in DRONES:
            topic = f"/sim/ground_truth/{drone}/pose"
            self.create_subscription(
                PoseStamped,
                topic,
                lambda msg, d=drone: self._on_pose(d, msg),
                10,
            )
            self.get_logger().info(f"subscribed to {topic}")

        # One publisher per ordered (observer, observed) pair.
        self._pubs = {}
        for observer in DRONES:
            for observed in DRONES:
                if observer == observed:
                    continue
                topic = f"/{observer}/coop/range_to/{observed}"
                self._pubs[(observer, observed)] = self.create_publisher(
                    PointStamped, topic, 10
                )
                self.get_logger().info(f"publishing {topic}")

        self._timer = self.create_timer(1.0 / PUBLISH_HZ, self._publish_all)
        self._tick = 0
        self.get_logger().info(
            f"ranging at {PUBLISH_HZ:.0f} Hz  |  "
            f"sigma_range={RANGE_SIGMA} m  sigma_bearing={BEARING_SIGMA} rad  |  "
            f"staleness_timeout={STALE_SEC} s"
        )

    # ------------------------------------------------------------------
    def _on_pose(self, drone, msg):
        self._latest[drone] = np.array([
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z,
        ])
        self._latest_time[drone] = time.monotonic()

    # ------------------------------------------------------------------
    def _publish_all(self):
        now = time.monotonic()
        self._tick += 1
        skipped = []

        for (observer, observed), pub in self._pubs.items():
            # Skip this pair if either pose is missing or stale.
            obs_t  = self._latest_time[observer]
            obsd_t = self._latest_time[observed]
            if obs_t is None or obsd_t is None:
                skipped.append(f"{observer}→{observed}(no data)")
                continue
            if (now - obs_t) > STALE_SEC or (now - obsd_t) > STALE_SEC:
                skipped.append(f"{observer}→{observed}(stale)")
                continue

            true_vec = self._latest[observed] - self._latest[observer]
            noisy_vec = self._apply_noise(true_vec)

            msg = PointStamped()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "world"
            msg.point.x = float(noisy_vec[0])
            msg.point.y = float(noisy_vec[1])
            msg.point.z = float(noisy_vec[2])
            pub.publish(msg)

        # Warn every 50 ticks (2 s) if any pairs are being skipped.
        if skipped and self._tick % 50 == 0:
            self.get_logger().warn(
                f"[tick {self._tick}] skipped pairs: {skipped}"
            )

    # ------------------------------------------------------------------
    def _apply_noise(self, vec: np.ndarray) -> np.ndarray:
        """Apply LiDAR-style range + bearing noise to a relative-position vector."""
        norm = np.linalg.norm(vec)
        if norm < 1e-6:
            return vec.copy()

        unit = vec / norm

        # Range noise: scale the unit vector by a noisy range.
        noisy_range = norm + self._rng.normal(0.0, RANGE_SIGMA)
        noisy_range = max(noisy_range, 0.0)

        # Bearing noise: add a small perpendicular perturbation.
        perp = self._perpendicular(unit)
        angle_noise = self._rng.normal(0.0, BEARING_SIGMA)
        noisy_unit = unit * np.cos(angle_noise) + perp * np.sin(angle_noise)
        noisy_unit /= np.linalg.norm(noisy_unit)

        return noisy_unit * noisy_range

    @staticmethod
    def _perpendicular(unit: np.ndarray) -> np.ndarray:
        """Return an arbitrary unit vector perpendicular to `unit`."""
        # Pick the axis least aligned with `unit` to avoid degeneracy.
        ref = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(unit, ref)) > 0.9:
            ref = np.array([0.0, 1.0, 0.0])
        perp = np.cross(unit, ref)
        return perp / np.linalg.norm(perp)


def main():
    rclpy.init()
    node = InterDroneRanging()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
