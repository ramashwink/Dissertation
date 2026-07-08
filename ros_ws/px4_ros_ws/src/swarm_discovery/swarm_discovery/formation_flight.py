#!/usr/bin/env python3
"""
formation_flight.py
===================
Commands all 5 PX4 SITL drones via offboard mode through ROS 2/XRCE-DDS.
Maintains formation spacing while executing a coordinated flight pattern.

Patterns:
  hover   — arm + takeoff + hold position (baseline motion experiment)
  square  — coordinated 8m square at 5m altitude, formation maintained
  circle  — coordinated circle, 4m radius per drone offset from spawn

Run AFTER the full ROS 2 stack is up:
    ros2 run swarm_discovery formation_flight
    ros2 run swarm_discovery formation_flight hover
    ros2 run swarm_discovery formation_flight square
    ros2 run swarm_discovery formation_flight circle

QGC connection ports (for monitoring):
    px4_1: 18570   px4_2: 18571   px4_3: 18572
    px4_4: 18573   px4_5: 18574
"""
import sys
import os
import math
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from px4_msgs.msg import OffboardControlMode, TrajectorySetpoint, VehicleCommand, VehicleStatus

PATTERN = sys.argv[1] if len(sys.argv) > 1 else "hover"

ARM_START_SEC   = 3.0    # wait for setpoint stream to establish before arming
ARM_RETRY_SEC   = 2.0    # resend SET_MODE+ARM this often until confirmed
ARM_TIMEOUT_SEC = 20.0   # give up and log a failure after this long

# Cheap file-based readiness signal for run_experiment_motion.sh to poll —
# spinning up `ros2 topic echo` repeatedly from bash costs a fresh DDS
# participant discovery each call, which adds CPU load right when the
# drones are already struggling to arm under a heavily oversubscribed CPU.
READY_MARKER = "/tmp/formation_flight_all_ready"

ALT    = -5.0     # NED: negative = up
SPEED  = 1.5      # m/s approx
SIDE   = 8.0      # square side length
RADIUS = 4.0      # circle radius

SPAWN = {
    "px4_1": [0.0, 0.0],
    "px4_2": [2.0, 0.0],
    "px4_3": [4.0, 0.0],
    "px4_4": [2.0, 2.0],
    "px4_5": [4.0, 2.0],
}

QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1)

STATUS_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5)


class FormationFlight(Node):
    def __init__(self):
        super().__init__("formation_flight")
        self.drones   = list(SPAWN.keys())
        self._mode    = {}
        self._sp      = {}
        self._cmd     = {}
        self._counter = 0

        self._armed             = {d: False for d in self.drones}
        self._offboard          = {d: False for d in self.drones}
        self._last_arm_try      = {d: -999.0 for d in self.drones}
        self._arm_failed_logged = {d: False for d in self.drones}
        self._ready_logged      = {d: False for d in self.drones}

        for drone in self.drones:
            self._mode[drone] = self.create_publisher(
                OffboardControlMode,
                f"/{drone}/fmu/in/offboard_control_mode", QOS)
            self._sp[drone] = self.create_publisher(
                TrajectorySetpoint,
                f"/{drone}/fmu/in/trajectory_setpoint", QOS)
            self._cmd[drone] = self.create_publisher(
                VehicleCommand,
                f"/{drone}/fmu/in/vehicle_command", QOS)
            self.create_subscription(
                VehicleStatus,
                f"/{drone}/fmu/out/vehicle_status_v4",
                lambda msg, d=drone: self._on_status(d, msg), STATUS_QOS)

        try:
            os.remove(READY_MARKER)
        except FileNotFoundError:
            pass

        self.t_start = time.monotonic()
        self.create_timer(0.1, self._tick)   # 10 Hz
        self.get_logger().info(
            f"[FORMATION] pattern={PATTERN}  alt={abs(ALT)}m  "
            f"All {len(self.drones)} drones — 10 Hz control loop")

    def _now_us(self):
        return int(self.get_clock().now().nanoseconds / 1000)

    def _on_status(self, drone, msg):
        self._armed[drone]    = (msg.arming_state == VehicleStatus.ARMING_STATE_ARMED)
        self._offboard[drone] = (msg.nav_state == VehicleStatus.NAVIGATION_STATE_OFFBOARD)

    def _send_mode(self, drone):
        msg           = OffboardControlMode()
        msg.position  = True
        msg.timestamp = self._now_us()
        self._mode[drone].publish(msg)

    def _send_sp(self, drone, x, y, z):
        msg          = TrajectorySetpoint()
        msg.position = [float(x), float(y), float(z)]
        msg.yaw      = 0.0
        msg.timestamp = self._now_us()
        self._sp[drone].publish(msg)

    def _send_cmd(self, drone, command, p1=0.0, p2=0.0):
        msg                  = VehicleCommand()
        msg.command          = command
        msg.param1           = float(p1)
        msg.param2           = float(p2)
        msg.target_system    = int(drone.split("_")[1]) + 1
        msg.target_component = 1
        msg.source_system    = 1
        msg.source_component = 1
        msg.from_external    = True
        msg.timestamp        = self._now_us()
        self._cmd[drone].publish(msg)

    def _get_target(self, drone, elapsed):
        ox, oy = SPAWN[drone]
        t = max(0.0, elapsed - 8.0)   # 8s arm/takeoff phase

        if PATTERN == "hover" or elapsed < 8.0:
            return ox, oy, ALT

        elif PATTERN == "square":
            period = (SIDE * 4) / SPEED
            phase  = (t % period) / period
            if   phase < 0.25: x, y = ox + SIDE*(phase*4),       oy
            elif phase < 0.50: x, y = ox + SIDE,                  oy + SIDE*(phase-0.25)*4
            elif phase < 0.75: x, y = ox + SIDE*(1-(phase-0.5)*4),oy + SIDE
            else:               x, y = ox,                         oy + SIDE*(1-(phase-0.75)*4)
            return x, y, ALT

        elif PATTERN == "circle":
            period = (2 * math.pi * RADIUS) / SPEED
            angle  = 2 * math.pi * (t % period) / period
            return ox + RADIUS*math.cos(angle), oy + RADIUS*math.sin(angle), ALT

        return ox, oy, ALT

    def _tick(self):
        elapsed = time.monotonic() - self.t_start

        for drone in self.drones:
            ox, oy = SPAWN[drone]
            x, y, z = self._get_target(drone, elapsed)

            self._send_mode(drone)
            self._send_sp(drone, x, y, z)

        # Retry ARM + OFFBOARD per drone until vehicle_status confirms both.
        # PX4 can drop out of OFFBOARD on its own (offboard-loss failsafe if
        # the setpoint stream stalls even briefly, e.g. under CPU load from
        # running 5 SITL instances + Gazebo at once) — so this never
        # permanently gives up, it just keeps re-arming for the whole flight
        # and logs periodically (not once) while a drone is stuck.
        if elapsed >= ARM_START_SEC:
            for drone in self.drones:
                if self._armed[drone] and self._offboard[drone]:
                    self._arm_failed_logged[drone] = False
                    continue
                if elapsed - self._last_arm_try[drone] < ARM_RETRY_SEC:
                    continue

                if elapsed - ARM_START_SEC > ARM_TIMEOUT_SEC and not self._arm_failed_logged[drone]:
                    self.get_logger().error(
                        f"[FORMATION] {drone} still not ARMED+OFFBOARD "
                        f"after {elapsed - ARM_START_SEC:.0f}s (armed={self._armed[drone]}, "
                        f"offboard={self._offboard[drone]}) — retrying")
                    self._arm_failed_logged[drone] = True

                self._last_arm_try[drone] = elapsed
                self._send_cmd(drone, VehicleCommand.VEHICLE_CMD_DO_SET_MODE, 1.0, 6.0)
                self._send_cmd(drone, VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, 1.0)
                self.get_logger().info(f"[FORMATION] ARM + OFFBOARD sent to {drone} (t={elapsed:.1f}s)")

            for d in self.drones:
                if self._armed[d] and self._offboard[d] and not self._ready_logged[d]:
                    self._ready_logged[d] = True
                    self.get_logger().info(f"[FORMATION] {d} confirmed ARMED+OFFBOARD (t={elapsed:.1f}s)")
                elif not (self._armed[d] and self._offboard[d]):
                    self._ready_logged[d] = False

            all_ready = all(self._armed[d] and self._offboard[d] for d in self.drones)
            if all_ready and not os.path.exists(READY_MARKER):
                with open(READY_MARKER, "w") as f:
                    f.write(f"{elapsed:.1f}\n")
                self.get_logger().info(f"[FORMATION] all 5 drones ARMED+OFFBOARD (t={elapsed:.1f}s)")
            elif not all_ready and os.path.exists(READY_MARKER):
                os.remove(READY_MARKER)

        if self._counter % 50 == 0:
            ox, oy = SPAWN["px4_1"]
            x, y, z = self._get_target("px4_1", elapsed)
            self.get_logger().info(
                f"[FORMATION] t={elapsed:.0f}s  pattern={PATTERN}  "
                f"px4_1 target=({x:.1f},{y:.1f},{abs(z):.1f}m)")

        self._counter += 1


def main():
    rclpy.init()
    node = FormationFlight()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
