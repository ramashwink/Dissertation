#!/bin/bash
# launch_ekf.sh  (mitigation-experiments branch)
# ================================================
# Launches the EKF baseline stack.
# Shares sensing + discovery with launch_wls.sh;
# if swarm_wls is already running, only the localisation
# window differs.
#
# Run standalone (sensing + discovery + EKF):
#   bash scripts/launch_ekf.sh
#
# Prerequisites: start_swarm.sh already running

set -e

WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
CODE="$HOME/Dissertation/code"
SESSION="swarm_ekf"

SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50 -n sensing

# ── Window 0: Sensing ────────────────────────────────────────────────────────
tmux send-keys -t $SESSION:sensing "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION:sensing
tmux send-keys -t $SESSION:sensing "$SRC && sleep 3 && python3 $CODE/inter_drone_ranging.py" Enter

# ── Window 1: Discovery ──────────────────────────────────────────────────────
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

# ── Window 2: EKF localisation × 5 ──────────────────────────────────────────
tmux new-window -t $SESSION -n ekf
tmux send-keys -t $SESSION:ekf \
  "$SRC && sleep 6 && \
  ros2 run swarm_discovery coop_loc_ekf px4_1 & \
  ros2 run swarm_discovery coop_loc_ekf px4_2 & \
  ros2 run swarm_discovery coop_loc_ekf px4_3 & \
  ros2 run swarm_discovery coop_loc_ekf px4_4 & \
  ros2 run swarm_discovery coop_loc_ekf px4_5 & wait" Enter

# ── Window 3: EKF attack logger ──────────────────────────────────────────────
tmux new-window -t $SESSION -n ekf_logger
tmux send-keys -t $SESSION:ekf_logger \
  "$SRC && sleep 8 && ros2 run swarm_discovery ekf_attack_logger" Enter
tmux split-window -v -t $SESSION:ekf_logger
tmux send-keys -t $SESSION:ekf_logger "$SRC" Enter
tmux send-keys -t $SESSION:ekf_logger "# Sybil:    ros2 run swarm_discovery sybil_registry_attack 3" Enter
tmux send-keys -t $SESSION:ekf_logger "# Replay:   ros2 run swarm_discovery replay_attack delayed" Enter
tmux send-keys -t $SESSION:ekf_logger "# Wormhole: ros2 run swarm_discovery wormhole_attack 0.05" Enter
tmux send-keys -t $SESSION:ekf_logger "# Analyse:  python3 ~/Dissertation/code/analyse_ekf_comparison.py sybil" Enter

echo ""
echo "[+] EKF stack launched in tmux session '$SESSION'"
echo "    tmux attach -t $SESSION"
echo ""
echo "    EKF vs WLS CSV: /tmp/ekf_vs_wls_comparison.csv"
echo "    Analyse: python3 ~/Dissertation/code/analyse_ekf_comparison.py [sybil|replay|wormhole]"
