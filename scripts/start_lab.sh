#!/bin/bash
echo "[*] Starting PX4 SITL lab environment..."
cd ~/PX4-Autopilot
make px4_sitl gz_x500 &
echo "[*] Waiting 30 seconds for PX4 to initialise..."
sleep 30
echo "[*] Lab ready — connect QGC to port 14550"
echo "[*] Then in pxh> run:"
echo "    param set MAV_0_BROADCAST 1"
echo "    mavlink start -u 18570 -o 14550 -t 172.24.224.223 -m onboard -r 4000000 -p"
echo "    commander takeoff"
