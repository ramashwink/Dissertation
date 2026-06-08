#!/bin/bash
# ============================================================
# start_swarm.sh — 3-drone PX4 SITL swarm
# Uses exact spawn commands confirmed working in lab
# ============================================================

PX4="$HOME/Dissertation/tools/PX4-Autopilot"
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"

source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"

# Kill leftovers
echo "[*] Cleaning up old processes..."
pkill -f "bin/px4"         2>/dev/null || true
pkill -f "MicroXRCEAgent"  2>/dev/null || true
pkill -f "gz sim"          2>/dev/null || true
sleep 2

# XRCE Agent
echo "[*] Starting Micro XRCE-DDS Agent..."
"$HOME/Dissertation/tools/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent" \
    udp4 -p 8888 > /tmp/xrce_agent.log 2>&1 &
AGENT_PID=$!
sleep 2

# CRITICAL: must cd into PX4-Autopilot so rcS can be found
cd "$PX4"

# Drone 1 — owns Gazebo server
echo "[*] Spawning px4_1 at (0,0)..."
PX4_SYS_AUTOSTART=4001 \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_1 \
    ./build/px4_sitl_default/bin/px4 -i 1 \
    > /tmp/px4_1.log 2>&1 &
PX4_1_PID=$!

echo "[*] Waiting 20s for Gazebo to start..."
sleep 20

# Drone 2 — joins Gazebo
echo "[*] Spawning px4_2 at (0,1)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="0,1" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_2 \
    ./build/px4_sitl_default/bin/px4 -i 2 \
    > /tmp/px4_2.log 2>&1 &
PX4_2_PID=$!
sleep 5

# Drone 3 — joins Gazebo
echo "[*] Spawning px4_3 at (0,2)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="0,2" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_3 \
    ./build/px4_sitl_default/bin/px4 -i 3 \
    > /tmp/px4_3.log 2>&1 &
PX4_3_PID=$!

echo ""
echo "[+] PIDs — agent:$AGENT_PID px4_1:$PX4_1_PID px4_2:$PX4_2_PID px4_3:$PX4_3_PID"
echo "[*] Waiting 15s for all drones to boot..."
sleep 15

echo ""
echo "[+] Swarm ready. Verify with:"
echo "    ros2 topic list | grep fmu | head -6"
echo "    head -5 /tmp/px4_1.log"
echo ""
echo "Then run: bash ~/Dissertation/scripts/launch_stack.sh"

trap "echo '[*] Shutting down...'; kill $PX4_1_PID $PX4_2_PID $PX4_3_PID $AGENT_PID 2>/dev/null" EXIT
wait
