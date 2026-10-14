"""Estimate pi by throwing random darts at a square: a tiny, CPU-only demo job.

    python monte_carlo_pi.py --workers 4
"""

import argparse
import math
import multiprocessing as mp
import os
import random
import socket
import time


def count_hits(samples: int, seed: int) -> int:
    rng = random.Random(seed)
    return sum(1 for _ in range(samples) if rng.random() ** 2 + rng.random() ** 2 <= 1.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=40_000_000)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1)))
    args = parser.parse_args()

    start = time.time()
    per_worker = args.samples // args.workers
    with mp.Pool(args.workers) as pool:
        hits = sum(pool.starmap(count_hits, [(per_worker, seed) for seed in range(args.workers)]))
    estimate = 4 * hits / (per_worker * args.workers)

    print(f"host={socket.gethostname()} workers={args.workers} samples={per_worker * args.workers:,}")
    print(f"pi ~ {estimate:.6f}  (error {abs(estimate - math.pi):.2e})  in {time.time() - start:.1f} s")


if __name__ == "__main__":
    main()
