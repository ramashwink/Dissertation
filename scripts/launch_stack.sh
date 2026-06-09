#!/bin/bash
# ============================================================
# launch_stack.sh — Design A (topic registry)
# Run AFTER start_swarm.sh has all three drones up
# ============================================================
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
CODE="$HOME/Dissertation/code"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"

SESSION="swarm"
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50

# Window 0: core stack
tmux send-keys -t $SESSION "$SRC && python3 $CODE/ground_truth_demux.py" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && python3 $CODE/inter_drone_ranging.py" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run swarm_discovery swarm_registry" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & ros2 run swarm_discovery swarm_heartbeat px4_2 0.0 1.0 0.0 & ros2 run swarm_discovery swarm_heartbeat px4_3 0.0 2.0 0.0 & wait" Enter

# Window 1: localisation + viz
tmux new-window -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run swarm_discovery coop_loc_dynamic px4_1 & ros2 run swarm_discovery coop_loc_dynamic px4_2 & ros2 run swarm_discovery coop_loc_dynamic px4_3 & wait" Enter

tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 map world & ros2 run swarm_discovery swarm_viz" Enter

# Window 2: attacks (ready to run)
tmux new-window -t $SESSION
tmux send-keys -t $SESSION "# ── ATTACKS ── source workspace first" Enter
tmux send-keys -t $SESSION "$SRC" Enter

echo ""
echo "[+] Stack launched in tmux session '$SESSION'"
echo "    tmux attach -t $SESSION"
echo ""
echo "Open RViz2 in a new terminal:"
echo "    source /opt/ros/humble/setup.bash"
echo "    source $WS/install/setup.bash"
echo "    ros2 run rviz2 rviz2"
echo "    → Fixed Frame: world"
echo "    → Add → By Topic → /swarm/viz/markers → MarkerArray"
echo ""
echo "── Attack commands (run from window 2 in tmux) ────────────"
echo "  Sybil:    ros2 run swarm_discovery sybil_registry_attack 3"
echo "  Replay:   ros2 run swarm_discovery replay_attack"
echo "  Wormhole: ros2 run swarm_discovery wormhole_attack"
echo "────────────────────────────────────────────────────────────"
