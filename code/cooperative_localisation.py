#!/usr/bin/env python3
"""
Cooperative localisation node -- step 3 of the cooperative-localisation stack.

One instance per drone. Subscribes to:
  - its own inter-drone range measurements:  /px4_N/coop/range_to/{neighbour}
  - each neighbour's broadcast position:     /px4_M/coop/self_estimate

Solves a weighted least-squares trilateration for this drone's position,
warm-started from the previous estimate, and publishes:
  - /px4_N/coop/self_estimate  (PoseStamped, world frame)
    so neighbours can use this drone as a moving anchor.

Algorithm: WLS trilateration as in Patwari et al. (IEEE SPM, 2005).
Each cycle minimises sum_i (||p - p_i|| - r_i)^2 over the drone's own
position p, using Levenberg-Marquardt with the previous estimate as
the initial guess. The warm start also resolves the geometric
underdetermination of 2-range 3D trilateration (two spheres intersect
on a circle) by anchoring the solver near the previous solution -- a
soft temporal prior, Kalman-flavoured without the bookkeeping.

What this node deliberately does NOT do (yet):
  - Feed the estimate into PX4 EKF2 via vehicle_visual_odometry.
    That's the closed-loop step and needs an ENU->NED frame
    conversion. Add once the open-loop estimates are seen to
    converge cleanly to ground truth.

Run one per drone in separate terminals (after step 1 + step 2 are up):
    python3 cooperative_localisation.py px4_1
    python3 cooperative_localisation.py px4_2
    python3 cooperative_localisation.py px4_3
"""
import sys
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped, PoseStamped
from scipy.optimize import least_squares


DRONES = ["px4_1", "px4_2", "px4_3"]

# Spawn positions in the Gazebo world (ENU). These match your
# PX4_GZ_MODEL_POSE launch args and serve as a priori initial conditions
# for the cooperative estimator, before any inter-drone measurements
# arrive. Match this to your actual swarm if you change spawn poses.
SPAWN_POSITIONS = {
    "px4_1": np.array([0.0, 0.0, 0.0]),
    "px4_2": np.array([0.0, 1.0, 0.0]),
    "px4_3": np.array([0.0, 2.0, 0.0]),
}

PUBLISH_HZ = 10.0  # cooperative loop rate


class CooperativeLocalisation(Node):
    def __init__(self, drone_ns):
        super().__init__("cooperative_localisation")
        self.ns = drone_ns
        self.neighbours = [d for d in DRONES if d != drone_ns]

        # Initial self-estimate: a priori spawn position.
        self.estimate = SPAWN_POSITIONS[drone_ns].copy()

        # Latest range observation TO each neighbour (the full 3D vector;
        # we extract magnitude as the range scalar at solve time).
        self.latest_range_vec = {n: None for n in self.neighbours}

        # Latest position estimate FROM each neighbour (their broadcast).
        # Bootstrap with spawn positions so the WLS can start solving the
        # moment we have ranges, even before neighbours have broadcast.
        self.latest_neighbour_pos = {
            n: SPAWN_POSITIONS[n].copy() for n in self.neighbours
        }

        # Subscriptions: our own outbound range measurements.
        for nbr in self.neighbours:
            topic = f"/{drone_ns}/coop/range_to/{nbr}"
            self.create_subscription(
                PointStamped, topic,
                lambda msg, n=nbr: self._on_range(n, msg),
                10,
            )
            self.get_logger().info(f"subscribed to {topic}")

        # Subscriptions: each neighbour's broadcast position estimate.
        for nbr in self.neighbours:
            topic = f"/{nbr}/coop/self_estimate"
            self.create_subscription(
                PoseStamped, topic,
                lambda msg, n=nbr: self._on_neighbour_est(n, msg),
                10,
            )
            self.get_logger().info(f"subscribed to {topic}")

        # Publisher: our own self-estimate, for neighbours.
        self.self_est_pub = self.create_publisher(
            PoseStamped, f"/{drone_ns}/coop/self_estimate", 10,
        )
        self.get_logger().info(f"publishing /{drone_ns}/coop/self_estimate")

        self.timer = self.create_timer(1.0 / PUBLISH_HZ, self._tick)
        self.iteration = 0
        self._first_solve_logged = False

    def _on_range(self, neighbour, msg):
        self.latest_range_vec[neighbour] = np.array([
            msg.point.x, msg.point.y, msg.point.z,
        ])

    def _on_neighbour_est(self, neighbour, msg):
        self.latest_neighbour_pos[neighbour] = np.array([
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z,
        ])

    def _tick(self):
        # Determine which neighbours have reported a range vector yet.
        ready = [n for n in self.neighbours if self.latest_range_vec[n] is not None]
        missing = [n for n in self.neighbours if self.latest_range_vec[n] is None]

        # Diagnostic: log missing neighbours every 20 ticks (2 s at 10 Hz)
        # so you can see in the terminal exactly who hasn't reported yet.
        if self.iteration % 20 == 0 and missing:
            self.get_logger().warn(
                f"[tick {self.iteration}] waiting for ranges from: {missing} "
                f"(ready: {ready})"
            )

        # Require at least one neighbour range before attempting a solve.
        # With only 1 neighbour available the system is under-determined
        # (3 residuals, 3 unknowns, no bearing diversity), so we hold the
        # previous estimate rather than emit a noisy solution.
        if len(ready) == 0:
            return

        # With a partial graph, solve using only the neighbours we have.
        new_estimate = self._solve_wls(active_neighbours=ready)
        if new_estimate is not None:
            self.estimate = new_estimate

        if not self._first_solve_logged and len(ready) == len(self.neighbours):
            self._first_solve_logged = True
            self.get_logger().info(
                f"first full cooperative solve: estimate = "
                f"[{self.estimate[0]:+.3f}, {self.estimate[1]:+.3f}, {self.estimate[2]:+.3f}]"
            )

        self._publish_self_estimate()
        self.iteration += 1

    def _solve_wls(self, active_neighbours=None):
        """Nonlinear WLS for own position given relative-vector measurements
        and neighbour positions.

        Uses the full 3D relative vector (range + bearing) per neighbour
        rather than range alone. With 2 neighbours this gives 6 residuals
        against 3 unknowns -- over-determined, well-posed, and not subject
        to the collinear-anchor rank deficiency that pure range-only
        trilateration suffers from with only 2 neighbours.

        Realistic for LiDAR-based cooperative localisation, since a LiDAR
        return provides both range and bearing. A UWB-based variant (range
        only) would need either more anchors or an additional sensor
        (e.g. altimeter) to be well-posed.

        active_neighbours: subset of self.neighbours that have reported ranges.
          Defaults to all neighbours (original behaviour). Enables partial-graph
          solving when one drone's topic is temporarily unavailable.
        """
        if active_neighbours is None:
            active_neighbours = self.neighbours

        # Safety guard: should never be called empty, but be explicit.
        if not active_neighbours:
            return None

        positions = np.array(
            [self.latest_neighbour_pos[n] for n in active_neighbours]
        )
        observed_vecs = np.array(
            [self.latest_range_vec[n] for n in active_neighbours]
        )

        def residuals(p):
            # Per-neighbour residual: predicted relative vector (anchor
            # minus self) minus observed relative vector (LiDAR return).
            # Flattened across all neighbours into a single 1D residual.
            predicted = positions - p[np.newaxis, :]
            return (predicted - observed_vecs).flatten()

        result = least_squares(
            residuals,
            self.estimate,    # warm start
            method="lm",      # Levenberg-Marquardt (m=6 > n=3, well-posed)
        )
        return result.x if result.success else None

    def _publish_self_estimate(self):
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.pose.position.x = float(self.estimate[0])
        msg.pose.position.y = float(self.estimate[1])
        msg.pose.position.z = float(self.estimate[2])
        msg.pose.orientation.w = 1.0
        self.self_est_pub.publish(msg)


def main():
    drone_ns = sys.argv[1] if len(sys.argv) > 1 else "px4_3"
    if drone_ns not in DRONES:
        print(f"unknown drone '{drone_ns}'; choose from {DRONES}")
        sys.exit(1)
    rclpy.init()
    node = CooperativeLocalisation(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
