#!/bin/bash
# Run AFTER launch_wls.sh — shares sensing layer, adds EKF nodes only
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"
SESSION="swarm_ekf"
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50

# EKF localisation × 5
tmux send-keys -t $SESSION "$SRC && \
ros2 run swarm_discovery coop_loc_ekf px4_1 & \
ros2 run swarm_discovery coop_loc_ekf px4_2 & \
ros2 run swarm_discovery coop_loc_ekf px4_3 & \
ros2 run swarm_discovery coop_loc_ekf px4_4 & \
ros2 run swarm_discovery coop_loc_ekf px4_5 & wait" Enter

# Comparison logger
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run swarm_discovery ekf_attack_logger" Enter

echo "[+] EKF stack: tmux attach -t $SESSION"
echo "    Comparison CSV: /tmp/ekf_vs_wls_comparison.csv"
echo "    Analyse: python3 ~/Dissertation/code/analyse_ekf_comparison.py sybil"
