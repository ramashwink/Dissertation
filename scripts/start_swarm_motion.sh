#!/bin/bash
# start_swarm_motion.sh
# Uses EXACT same launch method as working start_swarm.sh
# Only adds: isolated rootfs per instance

PX4="$HOME/Dissertation/tools/PX4-Autopilot"
WS="$HOME/Dissertation/ros_ws/px4_ros_ws"

source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"

echo "[*] Killing existing processes..."
pkill -f "bin/px4"        2>/dev/null || true
pkill -f "MicroXRCEAgent" 2>/dev/null || true
sleep 2

echo "[*] Cleaning runtime state..."
rm -rf /tmp/px4_* /tmp/px4-sock-* /tmp/px4_lock-*

echo "[*] Starting XRCE-DDS Agent..."
"$HOME/Dissertation/tools/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent" \
    udp4 -p 8888 > /tmp/xrce_agent.log 2>&1 &
XRCE_PID=$!
sleep 2

cd "$PX4"

echo "[*] Spawning px4_1 at (0,0) — owns Gazebo..."
PX4_SYS_AUTOSTART=4001 \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_1 \
    ./build/px4_sitl_default/bin/px4 -i 1 \
    > /tmp/px4_1.log 2>&1 &
PID_1=$!

echo "[*] Waiting 20s for Gazebo..."
sleep 20

echo "[*] Spawning px4_2 at (2,0)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="2,0" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_2 \
    ./build/px4_sitl_default/bin/px4 -i 2 \
    > /tmp/px4_2.log 2>&1 &
PID_2=$!
sleep 5

echo "[*] Spawning px4_3 at (4,0)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="4,0" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_3 \
    ./build/px4_sitl_default/bin/px4 -i 3 \
    > /tmp/px4_3.log 2>&1 &
PID_3=$!
sleep 5

echo "[*] Spawning px4_4 at (2,2)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="2,2" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_4 \
    ./build/px4_sitl_default/bin/px4 -i 4 \
    > /tmp/px4_4.log 2>&1 &
PID_4=$!
sleep 5

echo "[*] Spawning px4_5 at (4,2)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="4,2" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_5 \
    ./build/px4_sitl_default/bin/px4 -i 5 \
    > /tmp/px4_5.log 2>&1 &
PID_5=$!

echo "[+] PIDs: $PID_1 $PID_2 $PID_3 $PID_4 $PID_5"
echo "[*] Waiting 15s for all drones to boot..."
sleep 15

echo ""
echo "════════════════════════════════════════════════════"
echo "  [+] SWARM READY"
echo "  px4_1(0,0) px4_2(2,0) px4_3(4,0) px4_4(2,2) px4_5(4,2)"
echo "  QGC ports: 18571 18572 18573 18574 18575"
echo "  Logs: tail -f /tmp/px4_1.log"
echo "  Next: python3 ~/Dissertation/scripts/arm_all_drones.py"
echo "════════════════════════════════════════════════════"

# Set RC failsafe params on all drones
python3 ~/Dissertation/scripts/set_rc_params.py

trap "kill $PID_1 $PID_2 $PID_3 $PID_4 $PID_5 $XRCE_PID 2>/dev/null" EXIT
wait
