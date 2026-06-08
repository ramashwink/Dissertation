#!/usr/bin/env python3
"""
Ground-truth demux for the swarm-security testbed.

Subscribes directly to Gazebo's /world/default/pose/info via gz-transport
(bypassing ros_gz_bridge, which strips entity names from Pose_V -> TFMessage),
filters for the three drone-body entities by name, and republishes each as
geometry_msgs/PoseStamped on /sim/ground_truth/px4_N/pose.

This is the ground-truth source the rest of the cooperative-localisation
stack consumes:
    step 1 -- ground truth into ROS 2          (this node)
    step 2 -- inter-drone noisy ranging        (uses /sim/ground_truth/...)
    step 3 -- cooperative localisation node    (uses the ranges + neighbour
                                                broadcasts)

Run (after `sudo apt install python3-gz-transport13 python3-gz-msgs10` and
sourcing ROS 2):
    python3 ground_truth_demux.py
"""
import rclpy
from rclpy.node import Node as RosNode
from geometry_msgs.msg import PoseStamped

from gz.msgs10.pose_v_pb2 import Pose_V
from gz.transport13 import Node as GzNode


# Maps Gazebo entity names to our PX4 ROS namespaces. The keys must match
# exactly what `gz topic -e -t /world/default/pose/info` reports for the
# top-level drone-body poses (no subframe suffix like "/rotor_0").
DRONE_MAP = {
    "x500_1": "px4_1",
    "x500_2": "px4_2",
    "x500_3": "px4_3",
}
GZ_POSE_TOPIC = "/world/default/pose/info"

# Log every N inbound gz messages so you can see data is flowing without
# spamming the terminal. The full snapshot topic ticks at ~250 Hz.
LOG_EVERY_N = 250


class GroundTruthDemux(RosNode):
    def __init__(self):
        super().__init__("ground_truth_demux")

        self.pubs = {}
        for entity_name, ros_ns in DRONE_MAP.items():
            topic = f"/sim/ground_truth/{ros_ns}/pose"
            self.pubs[entity_name] = self.create_publisher(PoseStamped, topic, 10)
            self.get_logger().info(f"publishing {entity_name} -> {topic}")

        self.msgs_seen = 0

        # gz-transport callbacks run in their own thread. rclpy publishers
        # are thread-safe, so direct publish from the callback is fine.
        # If you ever need to do heavier processing here, latch into a dict
        # and have a ROS 2 timer publish from the latched values.
        self.gz_node = GzNode()
        ok = self.gz_node.subscribe(Pose_V, GZ_POSE_TOPIC, self._on_gz_pose)
        if not ok:
            self.get_logger().error(f"failed to subscribe to {GZ_POSE_TOPIC}")
        else:
            self.get_logger().info(f"subscribed to gz topic {GZ_POSE_TOPIC}")

    def _on_gz_pose(self, msg):
        # msg is a gz.msgs.Pose_V; iterate its repeated `pose` field.
        # The DRONE_MAP membership check filters out ground_plane, rotor
        # sub-frames, and anything else we don't care about.
        for pose in msg.pose:
            if pose.name in self.pubs:
                ps = PoseStamped()
                ps.header.stamp = self.get_clock().now().to_msg()
                ps.header.frame_id = "world"
                ps.pose.position.x = pose.position.x
                ps.pose.position.y = pose.position.y
                ps.pose.position.z = pose.position.z
                ps.pose.orientation.x = pose.orientation.x
                ps.pose.orientation.y = pose.orientation.y
                ps.pose.orientation.z = pose.orientation.z
                ps.pose.orientation.w = pose.orientation.w
                self.pubs[pose.name].publish(ps)

        self.msgs_seen += 1
        if self.msgs_seen % LOG_EVERY_N == 0:
            self.get_logger().info(f"ground truth flowing: {self.msgs_seen} gz frames processed")


def main():
    rclpy.init()
    node = GroundTruthDemux()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
