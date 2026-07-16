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
pkill -f "fastdds discovery" 2>/dev/null || true
pkill -f "fast-discovery-server-1.0.1" 2>/dev/null || true
sleep 2

echo "[*] Cleaning runtime state..."
rm -rf /tmp/px4_* /tmp/px4-sock-* /tmp/px4_lock-*
# Fast-DDS shared-memory/port-lock files only get cleaned up on a graceful
# shutdown; repeated kill -9's across a long session leak these and can
# degrade discovery for new participants. Safe to clear on every boot.
rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_* 2>/dev/null || true

# WSL2 doesn't reliably support IPv4 multicast, which Fast-DDS uses by
# default for participant discovery (SPDP) — causes silent, permanent
# publisher/subscriber discovery gaps for nodes that don't happen to start
# within a narrow early window (confirmed via `ip maddr show lo` showing
# zero IPv4 multicast groups joined, only IPv6). A custom unicast XML
# profile was tried first but proved unreliable itself (its initialPeersList
# had no port, so it could only ever reach one specific participant slot).
# Fast-DDS's own Discovery Server is the documented fix for exactly this
# scenario: one lightweight server all nodes register with via unicast,
# no multicast involved at all.
#
# IMPORTANT: must use the version-matched fast-discovery-server binary built
# from the SAME Fast-DDS 3.6.1 source tree as MicroXRCEAgent, NOT ROS2
# Humble's bundled fast-discovery-server (Fast-DDS 2.6.11). Confirmed
# 2026-07-13: the Agent's internal DDS participants (one per bridged PX4
# topic) never registered with a Fast-DDS-2.6.x-hosted Discovery Server —
# ros2 topic list saw zero px4 topics even with ROS_DISCOVERY_SERVER set and
# a correct SUPER_CLIENT XML profile loaded via FASTDDS_DEFAULT_PROFILES_FILE
# on the Agent. Building this project's own fast-discovery-server (via
# `cmake -DCOMPILE_TOOLS=ON` + `make fast-discovery-server` in
# tools/Micro-XRCE-DDS-Agent/build/fastdds/src/fastdds-build, binary at
# tools/fds/fast-discovery-server-1.0.1) and running it in SERVER mode
# (command index 42 — this build's CLI takes a numeric mode index as argv[1]
# rather than a text subcommand, since COMPILE_TOOLS built the raw fds tool
# without the ROS2-side python dispatcher that normally supplies that index)
# fixed it immediately — all 66 px4_N/fmu/... topics became visible.
echo "[*] Starting Fast-DDS discovery server (version-matched to Agent)..."
FDS_BIN="$HOME/Dissertation/tools/Micro-XRCE-DDS-Agent/build/fastdds/src/fastdds-build/tools/fds/fast-discovery-server-1.0.1"
"$FDS_BIN" 42 -i 0 -l 127.0.0.1 -p 11811 > /tmp/discovery_server.log 2>&1 &
DISCOVERY_PID=$!
sleep 1
export ROS_DISCOVERY_SERVER="127.0.0.1:11811"

echo "[*] Starting XRCE-DDS Agent..."
export FASTDDS_DEFAULT_PROFILES_FILE="$HOME/Dissertation/config/fastdds_agent_superclient.xml"
"$HOME/Dissertation/tools/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent" \
    udp4 -p 8888 > /tmp/xrce_agent.log 2>&1 &
XRCE_PID=$!
sleep 2

cd "$PX4"

echo "[*] Spawning px4_1 at (0,0) — owns Gazebo (headless, no GUI client)..."
HEADLESS=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_1 \
    ./build/px4_sitl_default/bin/px4 -i 1 \
    < <(sleep infinity) > /tmp/px4_1.log 2>&1 &
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
    < <(sleep infinity) > /tmp/px4_2.log 2>&1 &
PID_2=$!
sleep 5

echo "[*] Spawning px4_3 at (4,0)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="4,0" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_3 \
    ./build/px4_sitl_default/bin/px4 -i 3 \
    < <(sleep infinity) > /tmp/px4_3.log 2>&1 &
PID_3=$!
sleep 5

echo "[*] Spawning px4_4 at (2,2)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="2,2" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_4 \
    ./build/px4_sitl_default/bin/px4 -i 4 \
    < <(sleep infinity) > /tmp/px4_4.log 2>&1 &
PID_4=$!
sleep 5

echo "[*] Spawning px4_5 at (4,2)..."
PX4_GZ_STANDALONE=1 \
PX4_SYS_AUTOSTART=4001 \
PX4_GZ_MODEL_POSE="4,2" \
PX4_SIM_MODEL=gz_x500 \
PX4_UXRCE_DDS_NS=px4_5 \
    ./build/px4_sitl_default/bin/px4 -i 5 \
    < <(sleep infinity) > /tmp/px4_5.log 2>&1 &
PID_5=$!
sleep 5

echo "[+] PIDs: $PID_1 $PID_2 $PID_3 $PID_4 $PID_5"
echo "[*] Waiting 35s for all drones to boot..."
sleep 35

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

trap "kill $PID_1 $PID_2 $PID_3 $PID_4 $PID_5 $XRCE_PID $DISCOVERY_PID 2>/dev/null" EXIT
wait
