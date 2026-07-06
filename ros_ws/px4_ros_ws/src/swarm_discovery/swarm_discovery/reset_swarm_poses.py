#!/usr/bin/env python3
"""
reset_swarm_poses.py
=====================
Teleports every x500 model back to its nominal grid spawn position/
orientation in Gazebo via the /world/default/set_pose service.

Gazebo is started once by start_swarm_motion.sh and stays up for the
entire batch of experiment runs — PX4 arm/disarm and land only affect
the flight controller, not the physics-world model pose. If a drone
crashes, flips, or drifts during one run, it silently stays displaced
for every run after that. Call this before each experiment run to
guarantee a known-good starting state regardless of prior runs.

Usage:
    python3 reset_swarm_poses.py
"""
from gz.transport13 import Node
from gz.msgs10.pose_pb2 import Pose
from gz.msgs10.boolean_pb2 import Boolean

# Must match SPAWN in formation_flight.py and PX4_GZ_MODEL_POSE in
# start_swarm_motion.sh.
SPAWN = {
    "x500_1": (0.0, 0.0),
    "x500_2": (2.0, 0.0),
    "x500_3": (4.0, 0.0),
    "x500_4": (2.0, 2.0),
    "x500_5": (4.0, 2.0),
}

REST_Z   = 0.1   # small clearance above ground, matches natural spawn height
SERVICE  = "/world/default/set_pose"
TIMEOUT_MS = 2000


def reset_all():
    node = Node()
    ok_count = 0
    for name, (x, y) in SPAWN.items():
        req = Pose()
        req.name = name
        req.position.x = x
        req.position.y = y
        req.position.z = REST_Z
        req.orientation.x = 0.0
        req.orientation.y = 0.0
        req.orientation.z = 0.0
        req.orientation.w = 1.0

        result, rep = node.request(SERVICE, req, Pose, Boolean, TIMEOUT_MS)
        success = bool(result) and rep.data
        print(f"  reset {name} -> ({x}, {y}, {REST_Z}): {'OK' if success else 'FAILED'}")
        ok_count += int(success)

    return ok_count == len(SPAWN)


def main():
    import sys
    sys.exit(0 if reset_all() else 1)


if __name__ == "__main__":
    main()
