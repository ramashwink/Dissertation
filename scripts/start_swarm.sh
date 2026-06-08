#!/bin/bash
# ============================================================
# start_swarm.sh
# Full 3-drone PX4 SITL swarm + Micro XRCE-DDS Agent
# Matches confirmed spawn commands from lab sessions
# ============================================================

PX4="$HOME/Dissertation/tools/PX4-Autopilot"
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"

source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"

# ── Kill any leftover px4 / agent processes ───────────────────
echo "[*] Cleaning up old processes..."
pkill -f "bin/px4" 2>/dev/null || true
pkill -f "MicroXRCEAgent" 2>/dev/null || true
sleep 2

# ── Micro XRCE-DDS Agent ─────────────────────────────────────
echo "[*] Starting Micro XRCE-DDS Agent on UDP port 8888..."
"$HOME/Dissertation/tools/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent" \
    udp4 -p 8888 > /tmp/xrce_agent.log 2>&1 &
AGENT_PID=$!
sleep 2

# ── Drone 1: owns the Gazebo server ──────────────────────────
echo "[*] Spawning px4_1 (system ID 2) at (0,0)..."
cd "$PX4"
PX4_SYS_AUTOSTART=4001 \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_1 \
    ./build/px4_sitl_default/bin/px4 -i 1 \
    > /tmp/px4_1.log 2>&1 &
PX4_1_PID=$!

echo "[*] Waiting 15s for Gazebo to start..."
sleep 15

# ── Drone 2: joins existing Gazebo ───────────────────────────
echo "[*] Spawning px4_2 (system ID 3) at (0,1)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="0,1" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_2 \
    ./build/px4_sitl_default/bin/px4 -i 2 \
    > /tmp/px4_2.log 2>&1 &
PX4_2_PID=$!
sleep 5

# ── Drone 3: joins existing Gazebo ───────────────────────────
echo "[*] Spawning px4_3 (system ID 4) at (0,2)..."
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
echo "[+] Logs: /tmp/px4_1.log /tmp/px4_2.log /tmp/px4_3.log /tmp/xrce_agent.log"
echo ""
echo "[*] Waiting 15s for all drones to finish booting..."
sleep 15

echo ""
echo "[+] Swarm ready. Verify:"
echo "    ros2 topic list | grep fmu | head -6"
echo ""
echo "── Now open terminals for the stack ──────────────────────"
echo " T2: python3 ~/Dissertation/code/ground_truth_demux.py"
echo " T3: python3 ~/Dissertation/code/inter_drone_ranging.py"
echo " T4: ros2 run swarm_discovery swarm_registry"
echo " T5: ros2 run swarm_discovery swarm_heartbeat px4_1 0.0 0.0 0.0"
echo "     ros2 run swarm_discovery swarm_heartbeat px4_2 0.0 1.0 0.0"
echo "     ros2 run swarm_discovery swarm_heartbeat px4_3 0.0 2.0 0.0"
echo " T6: ros2 run swarm_discovery coop_loc_dynamic px4_1"
echo "     ros2 run swarm_discovery coop_loc_dynamic px4_2"
echo "     ros2 run swarm_discovery coop_loc_dynamic px4_3"
echo " T7: ros2 run swarm_discovery swarm_viz"
echo " T8: ros2 run rviz2 rviz2"
echo "──────────────────────────────────────────────────────────"
echo " ATTACK: ros2 run swarm_discovery sybil_registry_attack 3"
echo "──────────────────────────────────────────────────────────"

trap "echo '[*] Shutting down...'; kill $PX4_1_PID $PX4_2_PID $PX4_3_PID $AGENT_PID 2>/dev/null" EXIT
wait
