#!/bin/bash
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
CODE="$HOME/Dissertation/code"
SRC="source /opt/ros/humble/setup.bash && source $WS/install/setup.bash"
SESSION="swarm_wls"
tmux kill-session -t $SESSION 2>/dev/null || true
sleep 1
tmux new-session -d -s $SESSION -x 220 -y 50

tmux send-keys -t $SESSION "$SRC && python3 $CODE/ground_truth_demux.py" Enter
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && python3 $CODE/inter_drone_ranging.py" Enter
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run swarm_discovery swarm_registry" Enter
tmux split-window -v -t $SESSION
tmux send-keys -t $SESSION "$SRC && \
ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0 & \
ros2 run swarm_discovery swarm_heartbeat px4_2 0.0 1.0 0.0 & \
ros2 run swarm_discovery swarm_heartbeat px4_3 0.0 2.0 0.0 & \
ros2 run swarm_discovery swarm_heartbeat px4_4 0.0 3.0 0.0 & \
ros2 run swarm_discovery swarm_heartbeat px4_5 0.0 4.0 0.0 & wait" Enter

tmux new-window -t $SESSION
tmux send-keys -t $SESSION "$SRC && \
ros2 run swarm_discovery coop_loc_dynamic px4_1 & \
ros2 run swarm_discovery coop_loc_dynamic px4_2 & \
ros2 run swarm_discovery coop_loc_dynamic px4_3 & \
ros2 run swarm_discovery coop_loc_dynamic px4_4 & \
ros2 run swarm_discovery coop_loc_dynamic px4_5 & wait" Enter

tmux new-window -t $SESSION
tmux send-keys -t $SESSION "$SRC && ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 map world & ros2 run swarm_discovery swarm_viz" Enter

tmux new-window -t $SESSION
tmux send-keys -t $SESSION "$SRC" Enter
tmux send-keys -t $SESSION "# Sybil:    ros2 run swarm_discovery sybil_registry_attack 3" Enter
tmux send-keys -t $SESSION "# Replay:   ros2 run swarm_discovery replay_attack delayed" Enter
tmux send-keys -t $SESSION "# Wormhole: ros2 run swarm_discovery wormhole_attack 0.05" Enter

echo "[+] WLS stack: tmux attach -t $SESSION"
