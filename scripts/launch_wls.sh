#!/bin/bash
# launch_wls.sh  (mitigation-experiments branch)
# ================================================
# Launches the full WLS baseline stack in a tmux session.
# Fixed: paths now point at swarm_discovery ROS 2 package,
#        not ~/Dissertation/code (old location).
#
# Layers started:
#   Window 0 — sensing (ground_truth_demux + inter_drone_ranging)
#   Window 1 — discovery Design A (registry + 5 heartbeat clients)
#   Window 2 — WLS localisation (coop_loc_dynamic × 5)
#   Window 3 — visualisation + attack ready prompt
#
# Prerequisites: start_swarm.sh already running
# Usage: bash scripts/launch_wls.sh

set -e

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
PKG="$WS/src/swarm_discovery/swarm_discovery"
CODE="$HOME/Dissertation/code"
SESSION="swarm_wls"

SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50 -n sensing

# ── Window 0: Sensing ────────────────────────────────────────────────────────
tmux send-keys -t $SESSION:sensing "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION:sensing
tmux send-keys -t $SESSION:sensing "$SRC && sleep 3 && python3 $CODE/inter_drone_ranging.py" Enter

# ── Window 1: Discovery (Design A) ──────────────────────────────────────────
tmux new-window -t $SESSION -n discovery
tmux send-keys -t $SESSION:discovery "$SRC && ros2 run swarm_discovery swarm_registry" Enter
tmux split-window -v -t $SESSION:discovery
tmux send-keys -t $SESSION:discovery \
  "$SRC && sleep 3 && \
  ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_2 2.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_3 4.0 0.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_4 2.0 2.0 0.0 & \
  ros2 run swarm_discovery swarm_heartbeat px4_5 4.0 2.0 0.0 & wait" Enter

# ── Window 2: WLS localisation × 5 ──────────────────────────────────────────
tmux new-window -t $SESSION -n wls
tmux send-keys -t $SESSION:wls \
  "$SRC && sleep 6 && \
  ros2 run swarm_discovery coop_loc_dynamic px4_1 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_2 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_3 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_4 & \
  ros2 run swarm_discovery coop_loc_dynamic px4_5 & wait" Enter

# ── Window 3: Viz + attack prompt ───────────────────────────────────────────
tmux new-window -t $SESSION -n viz_attacks
tmux send-keys -t $SESSION:viz_attacks \
  "$SRC && ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 map world & \
  ros2 run swarm_discovery swarm_viz" Enter
tmux split-window -v -t $SESSION:viz_attacks
tmux send-keys -t $SESSION:viz_attacks "$SRC" Enter
tmux send-keys -t $SESSION:viz_attacks "# Sybil:    ros2 run swarm_discovery sybil_registry_attack 3" Enter
tmux send-keys -t $SESSION:viz_attacks "# Replay:   ros2 run swarm_discovery replay_attack delayed" Enter
tmux send-keys -t $SESSION:viz_attacks "# Wormhole: ros2 run swarm_discovery wormhole_attack 0.05" Enter

echo ""
echo "[+] WLS stack launched in tmux session '$SESSION'"
echo "    tmux attach -t $SESSION"
echo ""
echo "Windows:"
echo "  0 sensing    — ground_truth_demux + inter_drone_ranging"
echo "  1 discovery  — swarm_registry + 5 heartbeat clients"
echo "  2 wls        — coop_loc_dynamic × 5"
echo "  3 viz_attacks — swarm_viz + attack prompts"
