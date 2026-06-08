#!/usr/bin/env python3
"""
Swarm visualisation node
=========================
Closes the loop between the cooperative localisation stack and
a visual display. Publishes two outputs simultaneously:

  1. Gazebo native markers via gz-transport Marker API
     - Visible directly in the Gazebo GUI, no extra tool needed
     - Requires gz.msgs10 with marker_pb2 support

  2. ROS 2 visualization_msgs/MarkerArray on /swarm/viz/markers
     - Viewable in RViz2 (ros2 run rviz2 rviz2)
     - Works even if gz marker API is unavailable

What you see:
  TEAL spheres   — ground truth position of each real drone
  AMBER spheres  — WLS cooperative localisation estimate
  RED spheres    — ghost/Sybil drones from registry
  WHITE lines    — cooperative topology (who is ranging whom)
  YELLOW lines   — error vector (ground truth → estimate)

The error vector makes the attack visible in 3D:
  - Baseline: yellow lines are tiny (estimate ≈ truth)
  - Under Sybil attack: yellow lines grow as WLS is pulled
    toward ghost anchors

Run (after the full stack is up):
    python3 swarm_viz.py

Dependencies:
    pip install --break-system-packages pyquaternion  (optional, for orientation)
    ros2 run rviz2 rviz2  (to view MarkerArray output)
    Gazebo GUI must be open (to view gz markers)
"""
import sys
import math
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Point
from visualization_msgs.msg import Marker, MarkerArray
from std_msgs.msg import ColorRGBA, Header
from swarm_msgs.msg import SwarmRegistry

# ── Try gz-transport marker API ───────────────────────────────────────────────
try:
    from gz.msgs10.marker_pb2      import Marker as GzMarker
    from gz.msgs10.marker_v_pb2    import Marker_V as GzMarkerV
    from gz.msgs10.material_pb2    import Material as GzMaterial
    from gz.msgs10.color_pb2       import Color as GzColor
    from gz.msgs10.vector3d_pb2    import Vector3d as GzVector3d
    from gz.msgs10.pose_pb2        import Pose as GzPose
    from gz.transport13            import Node as GzNode
    GZ_AVAILABLE = True
    print("[VIZ] gz-transport Marker API available — will publish to Gazebo")
except ImportError:
    GZ_AVAILABLE = False
    print("[VIZ] gz-transport not available — RViz2 only mode")

# ── Configuration ─────────────────────────────────────────────────────────────
ALL_DRONES    = ["px4_1", "px4_2", "px4_3"]
UPDATE_HZ     = 25.0

# Marker IDs (must be unique per namespace in RViz2)
ID_GT_BASE    = 0    # 0-9:  ground truth spheres
ID_EST_BASE   = 10   # 10-19: estimate spheres
ID_ERR_BASE   = 20   # 20-29: error lines
ID_GHOST_BASE = 30   # 30-99: ghost drone spheres
ID_TOPO_BASE  = 100  # 100+:  topology lines

# Sphere sizes (metres)
GT_RADIUS     = 0.15
EST_RADIUS    = 0.12
GHOST_RADIUS  = 0.20

# Colors (RGBA 0-1)
C_GT    = (0.0,  0.8,  0.7,  0.85)   # teal  — ground truth
C_EST   = (1.0,  0.75, 0.0,  0.85)   # amber — WLS estimate
C_ERR   = (1.0,  1.0,  1.0,  0.6)    # white — error vector
C_GHOST = (0.9,  0.1,  0.1,  0.9)    # red   — ghost/Sybil
C_TOPO  = (0.5,  0.5,  1.0,  0.3)    # blue  — topology lines
# ─────────────────────────────────────────────────────────────────────────────


class SwarmViz(Node):
    def __init__(self):
        super().__init__("swarm_viz")

        # ── State ─────────────────────────────────────────────────────
        self.gt  = {d: None for d in ALL_DRONES}    # ground truth
        self.est = {d: None for d in ALL_DRONES}    # WLS estimate
        self.registry_members = []                   # live SwarmMember list

        # ── Subscribe: ground truth ───────────────────────────────────
        for drone in ALL_DRONES:
            self.create_subscription(
                PoseStamped,
                f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self._on_gt(d, msg),
                10,
            )

        # ── Subscribe: WLS estimates ──────────────────────────────────
        for drone in ALL_DRONES:
            self.create_subscription(
                PoseStamped,
                f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self._on_est(d, msg),
                10,
            )

        # ── Subscribe: registry (for ghost detection) ─────────────────
        self.create_subscription(
            SwarmRegistry, "/swarm/registry", self._on_registry, 10
        )

        # ── RViz2 MarkerArray publisher ───────────────────────────────
        self.marker_pub = self.create_publisher(
            MarkerArray, "/swarm/viz/markers", 10
        )

        # ── gz-transport setup ────────────────────────────────────────
        if GZ_AVAILABLE:
            self.gz_node = GzNode()
            self.gz_marker_pub = self.gz_node.advertise(
                "/marker", GzMarker
            )
            self.get_logger().info("[VIZ] gz marker publisher ready on /marker")

        self.create_timer(1.0 / UPDATE_HZ, self._tick)
        self.get_logger().info(
            f"[VIZ] Swarm visualisation running at {UPDATE_HZ} Hz\n"
            f"      RViz2: ros2 run rviz2 rviz2  →  add MarkerArray topic /swarm/viz/markers\n"
            f"      Frame: world"
        )

    # ── Callbacks ──────────────────────────────────────────────────────
    def _on_gt(self, drone, msg):
        self.gt[drone] = (
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z,
        )

    def _on_est(self, drone, msg):
        self.est[drone] = (
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z,
        )

    def _on_registry(self, msg):
        self.registry_members = list(msg.members)

    # ── Main tick ──────────────────────────────────────────────────────
    def _tick(self):
        markers = []
        stamp   = self.get_clock().now().to_msg()

        # Identify ghost drones (in registry but not in ALL_DRONES)
        ghost_members = [
            m for m in self.registry_members
            if m.drone_ns not in ALL_DRONES
        ]

        # ── Ground truth spheres (teal) ──────────────────────────────
        for i, drone in enumerate(ALL_DRONES):
            pos = self.gt.get(drone)
            if pos is None:
                continue
            markers.append(self._sphere(
                marker_id=ID_GT_BASE + i,
                ns="ground_truth",
                pos=pos,
                radius=GT_RADIUS,
                color=C_GT,
                label=drone,
                stamp=stamp,
            ))

        # ── WLS estimate spheres (amber) ─────────────────────────────
        for i, drone in enumerate(ALL_DRONES):
            est = self.est.get(drone)
            if est is None:
                continue
            # Offset slightly so it doesn't overlap gt sphere
            pos_offset = (est[0] + 0.05, est[1] + 0.05, est[2])
            markers.append(self._sphere(
                marker_id=ID_EST_BASE + i,
                ns="wls_estimate",
                pos=pos_offset,
                radius=EST_RADIUS,
                color=C_EST,
                label=f"{drone}_est",
                stamp=stamp,
            ))

        # ── Error vectors (gt → estimate, white lines) ───────────────
        for i, drone in enumerate(ALL_DRONES):
            gt  = self.gt.get(drone)
            est = self.est.get(drone)
            if gt is None or est is None:
                continue
            err = math.sqrt(sum((a - b) ** 2 for a, b in zip(gt, est)))
            # Only draw if error is meaningful (> 1 cm)
            if err > 0.01:
                markers.append(self._line(
                    marker_id=ID_ERR_BASE + i,
                    ns="error_vec",
                    p1=gt,
                    p2=est,
                    color=C_ERR,
                    width=0.02,
                    stamp=stamp,
                ))

        # ── Ghost drone spheres (red) ────────────────────────────────
        for i, ghost in enumerate(ghost_members):
            # Ghost position comes from their self_estimate topic
            # which the sybil attack publishes — use est dict if available
            pos = self.est.get(ghost.drone_ns)
            if pos is None:
                # Fall back to spawn position from registry
                pos = (ghost.spawn_x, ghost.spawn_y, ghost.spawn_z)
            markers.append(self._sphere(
                marker_id=ID_GHOST_BASE + i,
                ns="ghost_drones",
                pos=pos,
                radius=GHOST_RADIUS,
                color=C_GHOST,
                label=ghost.drone_ns,
                stamp=stamp,
            ))

        # ── Cooperative topology lines (blue) ────────────────────────
        # Draw a line between every pair of real drones with known gt
        line_id = ID_TOPO_BASE
        for i, d1 in enumerate(ALL_DRONES):
            for d2 in ALL_DRONES[i + 1:]:
                p1 = self.gt.get(d1)
                p2 = self.gt.get(d2)
                if p1 and p2:
                    markers.append(self._line(
                        marker_id=line_id,
                        ns="topology",
                        p1=p1,
                        p2=p2,
                        color=C_TOPO,
                        width=0.01,
                        stamp=stamp,
                    ))
                    line_id += 1

        # ── Publish RViz2 MarkerArray ─────────────────────────────────
        arr = MarkerArray()
        arr.markers = markers
        self.marker_pub.publish(arr)

        # ── Publish gz markers ────────────────────────────────────────
        if GZ_AVAILABLE:
            self._publish_gz_markers(markers)

    # ── RViz2 marker builders ──────────────────────────────────────────
    def _sphere(self, marker_id, ns, pos, radius, color, label, stamp):
        m = Marker()
        m.header.stamp    = stamp
        m.header.frame_id = "world"
        m.ns              = ns
        m.id              = marker_id
        m.type            = Marker.SPHERE
        m.action          = Marker.ADD
        m.pose.position.x = float(pos[0])
        m.pose.position.y = float(pos[1])
        m.pose.position.z = float(pos[2])
        m.pose.orientation.w = 1.0
        m.scale.x = m.scale.y = m.scale.z = float(radius * 2)
        m.color.r, m.color.g, m.color.b, m.color.a = color
        m.lifetime.sec    = 0
        m.lifetime.nanosec = int(0.5e9)   # auto-delete after 0.5s if not refreshed
        return m

    def _line(self, marker_id, ns, p1, p2, color, width, stamp):
        m = Marker()
        m.header.stamp    = stamp
        m.header.frame_id = "world"
        m.ns              = ns
        m.id              = marker_id
        m.type            = Marker.LINE_STRIP
        m.action          = Marker.ADD
        m.pose.orientation.w = 1.0
        m.scale.x         = float(width)
        m.color.r, m.color.g, m.color.b, m.color.a = color
        p = Point()
        p.x, p.y, p.z = float(p1[0]), float(p1[1]), float(p1[2])
        m.points.append(p)
        p2m = Point()
        p2m.x, p2m.y, p2m.z = float(p2[0]), float(p2[1]), float(p2[2])
        m.points.append(p2m)
        m.lifetime.sec    = 0
        m.lifetime.nanosec = int(0.5e9)
        return m

    # ── gz-transport marker publisher ──────────────────────────────────
    def _publish_gz_markers(self, ros_markers):
        """
        Convert RViz2 markers to gz Marker messages and publish.
        gz Marker API:
          action=0 ADD_MODIFY, action=2 DELETE_ALL
          type: 1=BOX, 2=CYLINDER, 3=SPHERE, 5=LINE_STRIP
        """
        for m in ros_markers:
            gz_m = GzMarker()
            gz_m.ns         = m.ns
            gz_m.id         = m.id
            gz_m.action     = 0        # ADD_MODIFY
            gz_m.lifetime.sec  = 0
            gz_m.lifetime.nsec = int(0.5e9)

            if m.type == Marker.SPHERE:
                gz_m.type = 3   # SPHERE
                gz_m.pose.position.x = m.pose.position.x
                gz_m.pose.position.y = m.pose.position.y
                gz_m.pose.position.z = m.pose.position.z
                gz_m.pose.orientation.w = 1.0
                gz_m.scale.x = m.scale.x
                gz_m.scale.y = m.scale.y
                gz_m.scale.z = m.scale.z
                mat = gz_m.material
                mat.ambient.r  = m.color.r
                mat.ambient.g  = m.color.g
                mat.ambient.b  = m.color.b
                mat.ambient.a  = m.color.a
                mat.diffuse.r  = m.color.r
                mat.diffuse.g  = m.color.g
                mat.diffuse.b  = m.color.b
                mat.diffuse.a  = m.color.a

            elif m.type == Marker.LINE_STRIP and len(m.points) >= 2:
                gz_m.type = 5   # LINE_STRIP
                for pt in m.points:
                    v = gz_m.point.add()
                    v.x, v.y, v.z = pt.x, pt.y, pt.z
                gz_m.scale.x = m.scale.x
                mat = gz_m.material
                mat.ambient.r  = m.color.r
                mat.ambient.g  = m.color.g
                mat.ambient.b  = m.color.b
                mat.ambient.a  = m.color.a

            try:
                self.gz_marker_pub.publish(gz_m)
            except Exception as e:
                self.get_logger().warn(f"gz marker publish failed: {e}", once=True)


def main():
    rclpy.init()
    node = SwarmViz()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
