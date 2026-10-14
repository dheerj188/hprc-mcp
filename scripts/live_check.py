"""Check the server against the real cluster the way an AI app uses it (stdio), with no AI involved.

On an HPRC login node it uses Slurm directly; on a laptop it uses your shared `ssh grace` session.

    uv run python scripts/live_check.py            # read-only checks
    uv run python scripts/live_check.py --submit   # also run a tiny 2-core job end to end
"""

import asyncio
import os
import sys
import time
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO = Path(__file__).resolve().parent.parent
SMOKE_JOB = """#!/bin/bash
#SBATCH --job-name=mcp_smoke
#SBATCH --time=00:05:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=2G
#SBATCH --partition=short

module purge
module load GCCcore/12.3.0 Python/3.11.3

cd "$SCRATCH/mcp_jobs"
python monte_carlo_pi.py --workers "$SLURM_CPUS_PER_TASK" --samples 2000000
"""


async def call(client: Client, tool: str, args: dict | None = None, show: int = 12) -> str:
    result = await client.call_tool(tool, args or {})
    body = "\n".join(block.text for block in result.content)
    mark = "FAIL" if result.is_error else "ok"
    print(f"\n[{mark}] {tool}({', '.join(f'{k}={v!r}' for k, v in (args or {}).items() if k != 'script')})")
    print("\n".join("    " + line for line in body.splitlines()[:show]))
    if result.is_error:
        raise SystemExit(f"\nStopped: {tool} failed.")
    return body


async def main() -> None:
    env = dict(os.environ)  # backend: auto (Slurm here, or ssh grace from a laptop)
    server = StdioServerParameters(command="uv", args=["run", "--directory", str(REPO), "hprc-mcp"], env=env)
    async with Client(server) as client:
        await call(client, "cluster_status")
        await call(client, "find_software", {"name": "Python"}, show=20)
        await call(client, "check_quota")
        await call(client, "my_jobs")
        has_sync = any(t.name == "sync_folder" for t in (await client.list_tools()).tools)
        if has_sync:
            await call(client, "sync_folder", {"name": "examples", "preview": True})
        if "--submit" not in sys.argv:
            print("\nRead-only checks passed. Run with --submit to test a real job.")
            return

        submitted = await call(client, "submit_job", {"script": SMOKE_JOB, "name": "mcp_smoke"})
        job_id = submitted.split()[2]
        deadline, state = time.time() + 900, ""
        while time.time() < deadline:
            details = (await client.call_tool("job_details", {"job_id": job_id})).content[0].text
            state = next((s for s in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "RUNNING", "PENDING")
                          if s in details), "UNKNOWN")
            print(f"    {time.strftime('%H:%M:%S')}  job {job_id}: {state}")
            if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                break
            await asyncio.sleep(20)
        await call(client, "job_details", {"job_id": job_id})
        await call(client, "job_output", {"job_id": job_id})
        print(f"\nEnd to end: job {job_id} finished as {state}.")


asyncio.run(main())
