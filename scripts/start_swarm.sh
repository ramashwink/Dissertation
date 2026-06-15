#!/bin/bash
# start_swarm.sh  (PATCHED: grid spawn poses to match algorithm/registry anchors)
# ==============================================================================
# Spawns the 5-drone swarm at the SAME grid the discovery/registry and all
# localisation nodes assume:
#     px4_1 (0,0)  px4_2 (2,0)  px4_3 (4,0)  px4_4 (2,2)  px4_5 (4,2)
#
# Previously px4_2..5 spawned on a line (0,1),(0,2),(0,3),(0,4) while the
# heartbeats / SPAWN_POSITIONS used the grid -> every estimator bootstrapped
# its neighbour anchors 2.24-4.47 m from the drones' real positions, biasing
# all error metrics. px4_1 is unchanged (origin == grid px4_1).
PX4="$HOME/Dissertation/tools/PX4-Autopilot"
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"

echo "[*] Cleaning up..."
pkill -f "bin/px4" 2>/dev/null || true
pkill -f "MicroXRCEAgent" 2>/dev/null || true
sleep 2

echo "[*] Starting XRCE-DDS Agent..."
"$HOME/Dissertation/tools/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent" \
    udp4 -p 8888 > /tmp/xrce_agent.log 2>&1 &
sleep 2

cd "$PX4"

echo "[*] Spawning px4_1 at (0,0) — owns Gazebo..."
PX4_SYS_AUTOSTART=4001 PX4_SIM_MODEL=gz_x500 PX4_UXRCE_DDS_NS=px4_1 \
    ./build/px4_sitl_default/bin/px4 -i 1 > /tmp/px4_1.log 2>&1 &
PX4_1=$!
echo "[*] Waiting 20s for Gazebo..."
sleep 20

echo "[*] Spawning px4_2 at (2,0)..."
PX4_GZ_STANDALONE=1 PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL_POSE="2,0" \
PX4_SIM_MODEL=gz_x500 PX4_UXRCE_DDS_NS=px4_2 \
    ./build/px4_sitl_default/bin/px4 -i 2 > /tmp/px4_2.log 2>&1 &
PX4_2=$!; sleep 5

echo "[*] Spawning px4_3 at (4,0)..."
PX4_GZ_STANDALONE=1 PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL_POSE="4,0" \
PX4_SIM_MODEL=gz_x500 PX4_UXRCE_DDS_NS=px4_3 \
    ./build/px4_sitl_default/bin/px4 -i 3 > /tmp/px4_3.log 2>&1 &
PX4_3=$!; sleep 5

echo "[*] Spawning px4_4 at (2,2)..."
PX4_GZ_STANDALONE=1 PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL_POSE="2,2" \
PX4_SIM_MODEL=gz_x500 PX4_UXRCE_DDS_NS=px4_4 \
    ./build/px4_sitl_default/bin/px4 -i 4 > /tmp/px4_4.log 2>&1 &
PX4_4=$!; sleep 5

echo "[*] Spawning px4_5 at (4,2)..."
PX4_GZ_STANDALONE=1 PX4_SYS_AUTOSTART=4001 PX4_GZ_MODEL_POSE="4,2" \
PX4_SIM_MODEL=gz_x500 PX4_UXRCE_DDS_NS=px4_5 \
    ./build/px4_sitl_default/bin/px4 -i 5 > /tmp/px4_5.log 2>&1 &
PX4_5=$!

echo "[+] PIDs: px4_1=$PX4_1 px4_2=$PX4_2 px4_3=$PX4_3 px4_4=$PX4_4 px4_5=$PX4_5"
echo "[*] Waiting 15s for all drones to boot..."
sleep 15
echo "[+] 5-drone swarm ready (grid layout). Run: bash ~/Dissertation/scripts/launch_stack.sh"
echo "[i] Verify spawn matches the grid:"
echo "    px4_1 (0,0)  px4_2 (2,0)  px4_3 (4,0)  px4_4 (2,2)  px4_5 (4,2)"

trap "kill $PX4_1 $PX4_2 $PX4_3 $PX4_4 $PX4_5 2>/dev/null" EXIT
wait
