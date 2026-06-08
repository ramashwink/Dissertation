from pymavlink import mavutil
import time, csv

print("[*] Recording baseline position for 30 seconds...")

conn = mavutil.mavlink_connection('udpin:0.0.0.0:14551')

# Ask PX4 to send to our port
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

with open('/home/msc-lab/baseline.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'x', 'y', 'z', 'vx', 'vy', 'vz'])
    
    start = time.time()
    while time.time() - start < 30:
        msg = conn.recv_match(type='LOCAL_POSITION_NED', blocking=False)
        if msg:
            writer.writerow([
                msg.time_boot_ms, msg.x, msg.y, msg.z,
                msg.vx, msg.vy, msg.vz
            ])
        time.sleep(0.01)

print("[+] Baseline saved to ~/baseline.csv")
print("[+] Now run attack and compare position deviation")
