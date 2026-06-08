import pandas as pd
import matplotlib.pyplot as plt
import glob, os

log_dir = os.path.expanduser('~/attack_logs/')

vvo_files = glob.glob(log_dir + '*visual_odometry*')
vvo = pd.read_csv(vvo_files[0]) if vvo_files else None

vlp_files = glob.glob(log_dir + '*vehicle_local_position*')
vlp = pd.read_csv(vlp_files[0]) if vlp_files else None

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Attack 1: LiDAR Position Spoofing — Empirical Evidence\n'
             'MSc Dissertation COMSM0117 — Ashwin Kotharamath',
             fontsize=13, fontweight='bold')

if vvo is not None:
    t = (vvo['timestamp'] - vvo['timestamp'].iloc[0]) / 1e6
    x = vvo['position[0]']
    y = vvo['position[1]']
    z = vvo['position[2]']

    # Plot 1 — X drift over time
    ax1 = axes[0, 0]
    ax1.plot(t, x, 'r-o', markersize=5, label='Spoofed X')
    ax1.set_title('Injected False X Position Over Time', fontweight='bold')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('X Position (m)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_facecolor('#fff5f5')

    # Plot 2 — Y drift over time
    ax2 = axes[0, 1]
    ax2.plot(t, y, '-o', markersize=5, color='darkorange', label='Spoofed Y')
    ax2.set_title('Injected False Y Position Over Time', fontweight='bold')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Y Position (m)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_facecolor('#fff5f5')

    # Plot 3 — 2D trajectory
    ax3 = axes[1, 0]
    ax3.plot(x, y, 'r-o', markersize=5, label='Spoofed trajectory')
    ax3.plot(x.iloc[0], y.iloc[0], 'go', markersize=12, label='Attack start', zorder=5)
    ax3.plot(x.iloc[-1], y.iloc[-1], 'rs', markersize=12, label='Attack end', zorder=5)
    ax3.set_title('2D Spoofed Position Trajectory', fontweight='bold')
    ax3.set_xlabel('X (m)')
    ax3.set_ylabel('Y (m)')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    ax3.set_facecolor('#fff5f5')

# Plot 4 — EKF2 response
ax4 = axes[1, 1]
if vlp is not None:
    t2 = (vlp['timestamp'] - vlp['timestamp'].iloc[0]) / 1e6
    ax4.plot(t2, vlp['x'], 'b-', linewidth=1, label='EKF2 X', alpha=0.8)
    ax4.plot(t2, vlp['y'], 'g-', linewidth=1, label='EKF2 Y', alpha=0.8)
    ax4.set_title('PX4 EKF2 Position Estimate During Attack', fontweight='bold')
    ax4.set_xlabel('Time (s)')
    ax4.set_ylabel('Position (m)')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    ax4.set_facecolor('#f5f5ff')
else:
    ax4.text(0.5, 0.5, 'vehicle_local_position\nnot in log',
             ha='center', va='center', transform=ax4.transAxes, fontsize=12)
    ax4.set_title('PX4 EKF2 Position Estimate', fontweight='bold')

plt.tight_layout()
out = os.path.expanduser('~/attack_evidence.png')
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f"[+] Plot saved to {out}")

if vvo is not None:
    total_drift = ((x.max()**2 + y.max()**2)**0.5)
    print(f"\n--- Attack 1 Summary: Position Spoofing ---")
    print(f"Spoofed messages accepted by PX4 EKF2 : {len(vvo)}")
    print(f"Max X displacement injected            : {x.max():.2f} m")
    print(f"Max Y displacement injected            : {y.max():.2f} m")
    print(f"Total 2D position displacement         : {total_drift:.2f} m")
    print(f"Attack duration                        : {t.iloc[-1]:.1f} s")
    print(f"\n[+] Copy to Windows:")
    print(f"    In WSL terminal: cp ~/attack_evidence.png /mnt/c/Users/MSc\\ Lab/Desktop/")
