#!/usr/bin/env python3
"""
PX4 offboard-control baseline for the swarm testbed.

Arms ONE namespaced drone, switches it to Offboard mode, and commands it to take
off and hold a fixed altitude. This is the "honest" behaviour your attacks will
degrade -- i.e. your experimental control condition.

Mirrors the official PX4 ROS 2 offboard example, adapted for a namespaced
multi-vehicle setup. Run one per drone in separate terminals (after sourcing
ROS 2 + your workspace) to get the whole swarm hovering:

    python3 px4_offboard_hover.py            # px4_3 (system id 4)
    python3 px4_offboard_hover.py px4_1      # px4_1 (system id 2)
    python3 px4_offboard_hover.py px4_2      # px4_2 (system id 3)

NOTE: this is open-loop (like the PX4 example) -- it does not read vehicle_status
to confirm arming succeeded. Watch the pxh> console or QGC. If the drone refuses
to arm, the console prints the failing preflight check.
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

from px4_msgs.msg import (
    OffboardControlMode,
    TrajectorySetpoint,
    VehicleCommand,
)

TAKEOFF_ALTITUDE_M = 3.0  # metres above start. NED frame -> published as -z.


class OffboardHover(Node):
    def __init__(self, drone_ns: str):
        super().__init__("px4_offboard_hover")
        self.ns = drone_ns

        # PX4 SITL sets MAV_SYS_ID = instance + 1, and you launched px4_N with
        # `-i N`, so the system id is N + 1.  px4_3 -> 4, px4_1 -> 2.
        # VehicleCommand.target_system MUST match, or the command is ignored.
        try:
            n = int(drone_ns.split("_")[-1])
        except ValueError:
            n = 0
        self.target_system = n + 1

        # Same BEST_EFFORT profile as the listener -- required for PX4 topics.
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.offboard_pub = self.create_publisher(
            OffboardControlMode, f"/{drone_ns}/fmu/in/offboard_control_mode", qos
        )
        self.setpoint_pub = self.create_publisher(
            TrajectorySetpoint, f"/{drone_ns}/fmu/in/trajectory_setpoint", qos
        )
        self.command_pub = self.create_publisher(
            VehicleCommand, f"/{drone_ns}/fmu/in/vehicle_command", qos
        )

        self.counter = 0
        self.timer = self.create_timer(0.1, self.loop)  # 10 Hz
        self.get_logger().info(
            f"Offboard hover for {drone_ns} (sys id {self.target_system}), "
            f"holding {TAKEOFF_ALTITUDE_M} m"
        )

    def _now_us(self) -> int:
        return int(self.get_clock().now().nanoseconds / 1000)

    def publish_offboard_mode(self):
        msg = OffboardControlMode()
        msg.timestamp = self._now_us()
        msg.position = True
        msg.velocity = False
        msg.acceleration = False
        msg.attitude = False
        msg.body_rate = False
        self.offboard_pub.publish(msg)

    def publish_setpoint(self):
        msg = TrajectorySetpoint()
        msg.timestamp = self._now_us()
        msg.position = [0.0, 0.0, -float(TAKEOFF_ALTITUDE_M)]  # up = negative z
        msg.yaw = 0.0
        self.setpoint_pub.publish(msg)

    def publish_command(self, command: int, param1: float = 0.0, param2: float = 0.0):
        msg = VehicleCommand()
        msg.timestamp = self._now_us()
        msg.command = command
        msg.param1 = float(param1)
        msg.param2 = float(param2)
        msg.target_system = self.target_system
        msg.target_component = 1
        msg.source_system = 1
        msg.source_component = 1
        msg.from_external = True
        self.command_pub.publish(msg)

    def loop(self):
        # Stream mode + setpoint every cycle. PX4 needs these at >2 Hz both
        # before arming (to permit offboard) and during flight (or it drops out
        # of offboard and fails safe).
        self.publish_offboard_mode()
        self.publish_setpoint()

        if self.counter == 10:
            # param1=1, param2=6 -> set custom main mode 6 == Offboard.
            self.publish_command(
                VehicleCommand.VEHICLE_CMD_DO_SET_MODE, param1=1.0, param2=6.0
            )
            # param1=1 -> arm.
            self.publish_command(
                VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, param1=1.0
            )
            self.get_logger().info("Sent offboard-mode + arm commands")

        if self.counter < 11:
            self.counter += 1


def main():
    drone_ns = sys.argv[1] if len(sys.argv) > 1 else "px4_3"
    rclpy.init()
    node = OffboardHover(drone_ns)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
