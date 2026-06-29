"""
swarm_config.py — single source of truth for swarm constants.
Import this in all localisation, attack, and viz nodes.
"""
DRONES = ["px4_1", "px4_2", "px4_3", "px4_4", "px4_5"]

SPAWN_POSITIONS = {
    "px4_1": [0.0, 0.0, 0.0],
    "px4_2": [2.0, 0.0, 0.0],
    "px4_3": [4.0, 0.0, 0.0],
    "px4_4": [2.0, 2.0, 0.0],
    "px4_5": [4.0, 2.0, 0.0],
}
