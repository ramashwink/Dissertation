#!/usr/bin/env python3
import sys, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = os.path.expanduser("~/Dissertation/evidence/figures")
os.makedirs(OUT_DIR, exist_ok=True)

LOG_FILES = {
    "sybil":    "/tmp/sybil_registry_attack_metrics.csv",
    "replay":   "/tmp/replay_attack_metrics.csv",
    "wormhole": "/tmp/wormhole_attack_metrics.csv",
}

DARK=  "#1a1a2e"
ACCENT="#e94560"
TEAL=  "#00b4d8"
AMBER= "#ffd60a"
WHITE= "#e0e0e0"

def style_ax(ax, title):
    ax.set_facecolor("#0f0f1a")
    ax.set_title(title, color=WHITE, fontsize=10, fontweight="bold", pad=8)
    ax.tick_params(colors=WHITE, labelsize=8)
    ax.xaxis.label.set_color(WHITE)
    ax.yaxis.label.set_color(WHITE)
    for sp in ax.spines.values():
        sp.set_edgecolor("#333355")
    ax.grid(True, alpha=0.15, color=WHITE)

def new_fig(title):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.patch.set_facecolor(DARK)
    fig.suptitle(f"{title}\nAshwin Kotharamath · 2678113 · COMSM0117",
                 color=WHITE, fontsize=13, fontweight="bold", y=0.98)
    return fig, axes

def error_panel(ax, t, err, label, color=ACCENT):
    ax.plot(t, err, color=color, linewidth=1.5, label=label)
    ax.fill_between(t, 0, err, color=color, alpha=0.15)
    peak = err.max()
    peak_t = t[err.argmax()]
    ax.axhline(peak, color=AMBER, linewidth=0.8, linestyle="--", alpha=0.7)
    ax.annotate(f"Peak: {peak:.3f} m", xy=(peak_t, peak),
                xytext=(peak_t + 2, peak * 0.85), color=AMBER, fontsize=8,
                arrowprops=dict(arrowstyle="->", color=AMBER, lw=0.8))
    ax.set_xlabel("Time (s)", color=WHITE)
    ax.set_ylabel("WLS Error (m)", color=WHITE)
    ax.legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)

def summary_panel(ax, stats):
    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.axis("off")
    lines = [f"{'ATTACK SUMMARY':^38}", "─"*38]
    for k,v in stats.items():
        lines.append(f"  {k:<26} {v}")
    ax.text(0.05, 0.95, "\n".join(lines), transform=ax.transAxes, fontsize=9,
            verticalalignment="top", fontfamily="monospace", color=WHITE,
            bbox=dict(facecolor="#0f0f1a", alpha=0.8, edgecolor=ACCENT,
                      boxstyle="round,pad=0.5"))

def save_fig(fig, name):
    out = os.path.join(OUT_DIR, f"{name}.png")
    fig.tight_layout(rect=[0,0,1,0.95])
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=DARK)
    plt.close(fig)
    print(f"[+] Saved: {out}")
    return out

def analyse_sybil(path):
    print(f"[SYBIL] Reading {path}")
    df = pd.read_csv(path)
    t  = df["t_s"].values
    e1 = pd.to_numeric(df.get("px4_1_error_m", pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    e3 = pd.to_numeric(df.get("px4_3_error_m", pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    ng = pd.to_numeric(df.get("num_ghosts",     pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    fig, axes = new_fig("Attack: Sybil / Ghost Drone Injection")
    error_panel(axes[0,0], t, e1, "px4_1 WLS error")
    style_ax(axes[0,0], "px4_1 (honest) — localisation error vs time")
    error_panel(axes[0,1], t, e3, "px4_3 WLS error", color=TEAL)
    style_ax(axes[0,1], "px4_3 (honest) — localisation error vs time")
    axes[1,0].plot(t, e1, color=ACCENT, linewidth=1.2, label="px4_1")
    axes[1,0].plot(t, e3, color=TEAL,   linewidth=1.2, label="px4_3")
    axes[1,0].set_xlabel("Time (s)", color=WHITE)
    axes[1,0].set_ylabel("WLS Error (m)", color=WHITE)
    axes[1,0].legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)
    style_ax(axes[1,0], "Combined error — both honest drones")
    summary_panel(axes[1,1], {
        "Duration (s)":         f"{t[-1]:.1f}",
        "Num ghost drones":     f"{int(ng.max())}",
        "Peak px4_1 error (m)": f"{e1.max():.4f}",
        "Peak px4_3 error (m)": f"{e3.max():.4f}",
        "Mean px4_1 error (m)": f"{e1.mean():.4f}",
        "STRIDE":               "Spoofing · Tampering",
        "Reference":            "Newsome et al. IPSN 2004",
    })
    style_ax(axes[1,1], "Summary")
    save_fig(fig, "sybil_attack")
    print(f"Peak px4_1={e1.max():.4f}m  px4_3={e3.max():.4f}m  mean={e1.mean():.4f}m")

def analyse_replay(path):
    print(f"[REPLAY] Reading {path}")
    df     = pd.read_csv(path)
    t      = df["t_s"].values
    phases = df["phase"].values
    age    = pd.to_numeric(df.get("msg_age_s",     pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    e1     = pd.to_numeric(df.get("px4_1_error_m", pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    e3     = pd.to_numeric(df.get("px4_3_error_m", pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    mode   = df["mode"].iloc[0] if "mode" in df.columns else "unknown"
    fig, axes = new_fig(f"Attack: Replay (mode={mode})")
    error_panel(axes[0,0], t, e1, "px4_1 WLS error")
    style_ax(axes[0,0], "px4_1 (honest) — localisation error vs time")
    error_panel(axes[0,1], t, e3, "px4_3 WLS error", color=TEAL)
    style_ax(axes[0,1], "px4_3 (honest) — localisation error vs time")
    axes[1,0].plot(t, age, color=AMBER, linewidth=1.2, label="Replayed msg age (s)")
    axes[1,0].set_xlabel("Time (s)", color=WHITE)
    axes[1,0].set_ylabel("Message Age (s)", color=WHITE)
    axes[1,0].legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)
    style_ax(axes[1,0], "Staleness of replayed measurements")
    attack = phases == "attack"
    summary_panel(axes[1,1], {
        "Mode":                 mode,
        "Delay (s)":            "5.0",
        "Peak px4_1 error (m)": f"{e1[attack].max() if attack.any() else 0:.4f}",
        "Peak px4_3 error (m)": f"{e3[attack].max() if attack.any() else 0:.4f}",
        "Mean px4_1 error (m)": f"{e1[attack].mean() if attack.any() else 0:.4f}",
        "Max msg age (s)":      f"{age.max():.2f}",
        "STRIDE":               "Spoofing · Denial of Service",
        "Reference":            "Ranganathan et al. 2024",
    })
    style_ax(axes[1,1], "Summary")
    save_fig(fig, "replay_attack")
    print(f"Peak px4_1={e1.max():.4f}m  px4_3={e3.max():.4f}m  age={age.max():.2f}s")

def analyse_wormhole(path):
    print(f"[WORMHOLE] Reading {path}")
    df      = pd.read_csv(path)
    t       = df["t_s"].values
    phases  = df["phase"].values
    true_d  = pd.to_numeric(df.get("true_dist_m",      pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    rep_d   = pd.to_numeric(df.get("reported_dist_m",   pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    est_sep = pd.to_numeric(df.get("est_separation_m",  pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    e1      = pd.to_numeric(df.get("px4_1_error_m",     pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    e3      = pd.to_numeric(df.get("px4_3_error_m",     pd.Series([0]*len(df))), errors="coerce").fillna(0).values
    scale   = df["scale"].iloc[0] if "scale" in df.columns else "?"
    fig, axes = new_fig(f"Attack: Wormhole (scale={scale})")
    error_panel(axes[0,0], t, e1, "px4_1 WLS error")
    style_ax(axes[0,0], "px4_1 (honest) — localisation error vs time")
    error_panel(axes[0,1], t, e3, "px4_3 WLS error", color=TEAL)
    style_ax(axes[0,1], "px4_3 (honest) — localisation error vs time")
    axes[1,0].plot(t, true_d,  color=TEAL,   linewidth=1.2, label="True dist (m)")
    axes[1,0].plot(t, rep_d,   color=ACCENT,  linewidth=1.2, label="Reported dist (m)")
    axes[1,0].plot(t, est_sep, color=AMBER,   linewidth=1.2, linestyle="--", label="Est separation (m)")
    axes[1,0].set_xlabel("Time (s)", color=WHITE)
    axes[1,0].set_ylabel("Distance (m)", color=WHITE)
    axes[1,0].legend(fontsize=8, facecolor="#0f0f1a", labelcolor=WHITE)
    style_ax(axes[1,0], "True vs reported inter-drone distance")
    attack = phases == "attack"
    summary_panel(axes[1,1], {
        "Scale":                   f"{scale}",
        "True dist (m)":           f"{true_d[attack].mean():.3f}" if attack.any() else "n/a",
        "Reported dist (m)":       f"{rep_d[attack].mean():.3f}"  if attack.any() else "n/a",
        "Min est separation (m)":  f"{est_sep[attack].min():.3f}" if attack.any() else "n/a",
        "Peak px4_1 error (m)":    f"{e1.max():.4f}",
        "Peak px4_3 error (m)":    f"{e3.max():.4f}",
        "STRIDE":                  "Tampering · EoP",
        "Reference":               "Hu Perrig Johnson JSAC 2006",
    })
    style_ax(axes[1,1], "Summary")
    save_fig(fig, "wormhole_attack")
    print(f"Peak px4_1={e1.max():.4f}m  px4_3={e3.max():.4f}m  est_sep_min={est_sep.min():.4f}m")

def main():
    target  = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    targets = list(LOG_FILES.keys()) if target == "all" else [target]
    for name in targets:
        path = LOG_FILES.get(name)
        if not path:
            print(f"Unknown: {name}"); continue
        if not os.path.exists(path):
            print(f"[!] Log not found: {path}"); continue
        if   name == "sybil":    analyse_sybil(path)
        elif name == "replay":   analyse_replay(path)
        elif name == "wormhole": analyse_wormhole(path)
    print(f"\n[+] Figures saved to {OUT_DIR}/")

if __name__ == "__main__":
    main()
