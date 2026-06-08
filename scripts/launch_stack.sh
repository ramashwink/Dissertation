#!/bin/bash
# ============================================================
# launch_stack.sh
# Launches the full cooperative localisation + viz stack
# using tmux — one pane per component
# Run AFTER start_swarm.sh has all three drones up
# ============================================================

source /opt/ros/humble/setup.bash
source "$HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash"

SESSION="swarm"
CODE="$HOME/Dissertation/code"

# Kill existing session if any
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1

# Create session
tmux new-session -d -s $SESSION -x 220 -y 50

# Pane 0: ground truth
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && python3 $CODE/ground_truth_demux.py" Enter

# Pane 1: ranging
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && python3 $CODE/inter_drone_ranging.py" Enter

# Pane 2: registry
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && ros2 run swarm_discovery swarm_registry" Enter

# Pane 3: heartbeats (all 3 in one pane)
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && \
ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & \
ros2 run swarm_discovery swarm_heartbeat px4_2 0.0 1.0 0.0 & \
ros2 run swarm_discovery swarm_heartbeat px4_3 0.0 2.0 0.0 & wait" Enter

# Pane 4: coop localisation (all 3 in one pane)
tmux new-window -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && \
ros2 run swarm_discovery coop_loc_dynamic px4_1 & \
ros2 run swarm_discovery coop_loc_dynamic px4_2 & \
ros2 run swarm_discovery coop_loc_dynamic px4_3 & wait" Enter

# Pane 5: visualisation
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && ros2 run swarm_discovery swarm_viz" Enter

# Pane 6: attack — ready but not launched
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "# Attack ready — run when baseline is established:" Enter
tmux send-keys -t $SESSION "# ros2 run swarm_discovery sybil_registry_attack 3" Enter

echo ""
echo "[+] Stack launched in tmux session '$SESSION'"
echo "    tmux attach -t $SESSION     — attach to view all panes"
echo "    Ctrl+B then D               — detach without killing"
echo "    Ctrl+B then arrow keys      — switch panes"
echo ""
echo "[+] Open RViz2 separately:"
echo "    source /opt/ros/humble/setup.bash"
echo "    source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash"
echo "    ros2 run rviz2 rviz2"
echo "    → Add → By Topic → /swarm/viz/markers → MarkerArray"
echo "    → Fixed Frame: world"
