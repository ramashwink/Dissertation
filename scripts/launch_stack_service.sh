#!/bin/bash
# ============================================================
# launch_stack_service.sh — Design B (service-based registry)
# Switch from launch_stack.sh by running this instead
# ============================================================
source /opt/ros/humble/setup.bash
source "$HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash"

SESSION="swarm_svc"
CODE="$HOME/Dissertation/code"

tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50

tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && python3 $CODE/ground_truth_demux.py" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && python3 $CODE/inter_drone_ranging.py" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && ros2 run swarm_discovery swarm_registry_service" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && sleep 3 && ros2 run swarm_discovery swarm_client px4_1 0.0 0.0 0.0 & ros2 run swarm_discovery swarm_client px4_2 0.0 1.0 0.0 & ros2 run swarm_discovery swarm_client px4_3 0.0 2.0 0.0 & wait" Enter

tmux new-window -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && ros2 run swarm_discovery coop_loc_dynamic px4_1 & ros2 run swarm_discovery coop_loc_dynamic px4_2 & ros2 run swarm_discovery coop_loc_dynamic px4_3 & wait" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "source /opt/ros/humble/setup.bash && source $HOME/Dissertation/ros_ws/px4_ros_ws/install/setup.bash && ros2 run swarm_discovery swarm_viz" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "# Sybil attack (Design B) — will be REJECTED by allowlist:" Enter
tmux send-keys -t $SESSION "# ros2 run swarm_discovery sybil_service_attack" Enter

echo "[+] Design B stack in tmux session '$SESSION'"
echo "    tmux attach -t $SESSION"
echo ""
echo "Compare designs:"
echo "  Design A (vulnerable):  tmux attach -t swarm"
echo "  Design B (mitigated):   tmux attach -t swarm_svc"
