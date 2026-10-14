"""Find the launch angle that throws a projectile farthest when air drag is included.

Without drag the answer is 45 degrees; with quadratic drag it is lower. Each worker
simulates a range of angles (simple Euler integration). Pure Python, CPU only.

    python projectile_drag.py --workers 4 --speed 50
"""

import argparse
import math
import multiprocessing as mp
import os


def flight_range(angle_deg: float, speed: float, drag: float, dt: float = 1e-4) -> float:
    vx, vy = speed * math.cos(math.radians(angle_deg)), speed * math.sin(math.radians(angle_deg))
    x = y = 0.0
    while y >= 0.0:
        v = math.hypot(vx, vy)
        vx -= drag * v * vx * dt
        vy -= (9.81 + drag * v * vy) * dt
        x, y = x + vx * dt, y + vy * dt
    return x


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed", type=float, default=50.0, help="launch speed in m/s")
    parser.add_argument("--drag", type=float, default=0.002, help="drag coefficient per metre")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1)))
    args = parser.parse_args()

    angles = [a / 2 for a in range(40, 101)]  # 20 to 50 degrees in half-degree steps
    with mp.Pool(args.workers) as pool:
        ranges = pool.starmap(flight_range, [(a, args.speed, args.drag) for a in angles])
    best = max(range(len(angles)), key=ranges.__getitem__)
    print(f"speed={args.speed} m/s drag={args.drag} workers={args.workers}")
    print(f"best angle = {angles[best]:.1f} deg, range = {ranges[best]:.1f} m (no-drag optimum is 45 deg)")


if __name__ == "__main__":
    main()
