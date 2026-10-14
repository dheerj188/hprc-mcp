"""How the server reaches the cluster.

LocalBackend  runs Slurm commands directly. Use it when the AI app runs on an HPRC login node.
SSHBackend    runs the same commands through the user's own shared SSH session (a plain
              `ssh grace` with connection sharing turned on), for an AI app on a laptop.
              The server never sees a password.
MockBackend   is a pretend cluster for tests, laptops and live-demo fallbacks.

Safety rules shared by all of them: the AI can only see, read and cancel jobs submitted through
this server (their working directory is $SCRATCH/<jobs_dir>), can only list that folder, and
there is no operation that deletes or edits files.
"""

from __future__ import annotations

import itertools
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from .config import SyncPair

_JOB_ID = re.compile(r"^\d+$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_SOFTWARE = re.compile(r"^[A-Za-z0-9._+/-]{1,80}$")

NOT_CONNECTED = (
    "Not connected to {host}: there is no active login session, so the cluster cannot be reached. "
    "Tell the user this and stop. Only the user can log in (by running `ssh grace` in their own terminal, "
    "with their password and a Duo push). Do not search the computer, run other commands or try to log in."
)
NOT_OURS = (
    "Job {job_id} was not submitted through this server, so for safety it cannot be inspected or "
    "cancelled here. This server only works with its own jobs."
)


def check_job_id(job_id: str) -> str:
    job_id = str(job_id).strip()
    if not _JOB_ID.match(job_id):
        raise ToolError(f"'{job_id}' is not a Slurm job ID (expected digits, e.g. 1234567).")
    return job_id


def check_name(name: str, what: str = "name") -> str:
    if not _SAFE_NAME.match(name):
        raise ToolError(f"Invalid {what} '{name}': use only letters, digits, '.', '_', '+' or '-'.")
    return name


def check_software(name: str) -> str:
    if not _SOFTWARE.match(name):
        raise ToolError(f"Invalid software name '{name}'.")
    return name


class ShellBackend:
    """The operations, as ordinary Slurm/Linux commands. Subclasses decide where they run."""

    where = "the cluster"

    def __init__(self, jobs_dir: str):
        self.jobs_dir = jobs_dir
        self.jobs = f'"$SCRATCH"/{shlex.quote(jobs_dir)}'  # shell expression, expanded on the cluster
        self._jobs_abs: str | None = None

    def connected(self) -> bool:
        raise NotImplementedError

    def _argv(self, command: str) -> list[str]:
        raise NotImplementedError

    def _lost_connection(self, returncode: int) -> bool:
        return False

    def run(self, command: str, stdin: str | None = None, timeout: int = 60) -> str:
        if not self.connected():
            raise ToolError(NOT_CONNECTED.format(host=self.where))
        try:
            done = subprocess.run(self._argv(command), input=stdin, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ToolError(f"The cluster did not answer within {timeout} seconds.") from None
        if self._lost_connection(done.returncode):
            raise ToolError(NOT_CONNECTED.format(host=self.where))
        output = (done.stdout + done.stderr).strip()
        if done.returncode != 0:
            raise ToolError(f"The command failed on the cluster (exit code {done.returncode}):\n{output[-2000:]}")
        return output

    @property
    def jobs_abs(self) -> str:
        if self._jobs_abs is None:
            self._jobs_abs = self.run(f"echo {self.jobs}").splitlines()[-1].strip().rstrip("/")
        return self._jobs_abs

    def _require_own_job(self, job_id: str) -> None:
        out = self.run(f"sacct -j {job_id} -X -n -P --format=WorkDir")
        workdirs = [line.strip().rstrip("/") for line in out.splitlines() if line.strip().startswith("/")]
        if not workdirs:
            raise ToolError(f"Job {job_id} was not found.")
        if workdirs[-1] != self.jobs_abs:
            raise ToolError(NOT_OURS.format(job_id=job_id))

    def cluster_status(self) -> str:
        return self.run("sinfo -s")

    def my_jobs(self) -> str:
        out = self.run('squeue -u "$USER" -h -o "%i|%P|%j|%T|%M|%l|%R|%Z"')
        rows = [line.split("|") for line in out.splitlines() if line.count("|") == 7]
        mine = [r for r in rows if r[7].rstrip("/") == self.jobs_abs]
        header = f"{'JOBID':>10} {'PARTITION':>10} {'NAME':>20} {'STATE':>9} {'TIME':>10} {'LIMIT':>10}  NODE/REASON"
        lines = [f"{r[0]:>10} {r[1]:>10} {r[2][:20]:>20} {r[3]:>9} {r[4]:>10} {r[5]:>10}  {r[6]}" for r in mine]
        return "\n".join([header, *lines]) if lines else header + "\n(no jobs from this server are queued or running)"

    def submit(self, script: str, name: str) -> str:
        log = f"{self.jobs}/logs/%j.out"
        out = self.run(
            f"mkdir -p {self.jobs}/logs && cd {self.jobs} && cat > {name}.slurm && "
            f"sbatch --parsable --chdir={self.jobs} --output={log} --error={log} {name}.slurm",
            stdin=script,
        )
        return out.splitlines()[-1].split(";")[0].strip()

    def job_details(self, job_id: str) -> str:
        self._require_own_job(job_id)
        return self.run(
            f"sacct -j {job_id} -X --format=JobID,JobName%25,Partition,State,ExitCode,Elapsed,Timelimit,AllocCPUS,NodeList"
        )

    def job_output(self, job_id: str, lines: int) -> str:
        log = f"{self.jobs}/logs/{job_id}.out"  # only this server's jobs write here
        return self.run(
            f"if [ -f {log} ]; then tail -n {lines} {log}; "
            f"else echo 'No output yet (the job may still be waiting in the queue).'; fi"
        )

    def cancel(self, job_id: str) -> str:
        self._require_own_job(job_id)
        self.run(f"scancel {job_id}")
        return f"Cancel request sent for job {job_id}."

    def find_software(self, name: str) -> str:
        terse = "" if "/" in name else "-t "  # a full name like Python/3.11.5 shows how to load it
        return self.run(f"module {terse}spider {shlex.quote(name)} 2>&1 | head -n 60")

    def quota(self) -> str:
        return self.run('showquota 2>&1 || df -h "$HOME" "$SCRATCH"')

    def list_files(self) -> str:
        return self.run(f"mkdir -p {self.jobs} && ls -la {self.jobs} {self.jobs}/logs 2>/dev/null || ls -la {self.jobs}")

    def copy_to_cluster(self, local: Path) -> str:
        dest = f"{self.jobs}/{shlex.quote(local.name)}"
        return self.run(f"mkdir -p {self.jobs} && cat > {dest} && echo {dest}", stdin=local.read_text())


class LocalBackend(ShellBackend):
    """For an AI app running on the cluster's login node: run the commands right here."""

    where = "this login node"

    def connected(self) -> bool:
        return shutil.which("sbatch") is not None

    def _argv(self, command: str) -> list[str]:
        return ["bash", "-lc", command]


class SSHBackend(ShellBackend):
    """For an AI app on a laptop: send the commands through the user's shared SSH session."""

    def __init__(self, host: str, control_path: str, jobs_dir: str):
        super().__init__(jobs_dir)
        self.host = self.where = host
        self.control_path = control_path

    def _control(self, action: str) -> subprocess.CompletedProcess:
        """Ask the local shared-login process something (check / exit). No network, no password prompt."""
        command = ["ssh", "-o", f"ControlPath={self.control_path}", "-O", action, self.host]
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(command, 255, "", "timed out")

    def connected(self) -> bool:
        """Is the shared login session open?"""
        return self._control("check").returncode == 0

    def session_age(self) -> str | None:
        """How long the shared login has been open, e.g. '01:23:45', if it is open."""
        found = re.search(r"pid=(\d+)", self._control("check").stderr)
        if not found:
            return None
        age = subprocess.run(["ps", "-o", "etime=", "-p", found.group(1)], capture_output=True, text=True)
        return age.stdout.strip() or None

    def end_session(self) -> str:
        """Close the shared login (the same as `ssh -O exit grace`)."""
        if not self.connected():
            return f"There was no open login session to {self.host}; nothing to close."
        self._control("exit")
        if self.connected():
            raise ToolError(f"Could not close the login session. The user can run `ssh -O exit {self.host}`.")
        return (
            f"Closed the shared login to {self.host}. Cluster tools will now answer 'not connected'. "
            f"To use the cluster again, the user runs `ssh {self.host}` (password + Duo)."
        )

    def _argv(self, command: str) -> list[str]:
        return [
            "ssh", "-o", "BatchMode=yes", "-o", "ControlMaster=no",
            "-o", f"ControlPath={self.control_path}", self.host, "bash -lc " + shlex.quote(command),
        ]

    def _lost_connection(self, returncode: int) -> bool:
        return returncode == 255  # ssh itself failed, e.g. the session dropped mid-call

    def sync(self, pair: SyncPair, preview: bool) -> str:
        """rsync a configured folder pair through the same shared SSH session (never deletes)."""
        scratch = self.run('echo "$SCRATCH"').splitlines()[-1].strip()
        target = f"{scratch}/{pair.remote}"
        ssh = f"ssh -o BatchMode=yes -o ControlMaster=no -o ControlPath={self.control_path}"
        command = ["rsync", "-az", "--out-format=%n", "-e", ssh, *(f"--exclude={p}" for p in pair.exclude)]
        if preview:
            command.append("--dry-run")
        if pair.direction == "push":
            self.run(f"mkdir -p {shlex.quote(target)}")
            command += [f"{pair.local}/", f"{self.host}:{target}/"]
        else:
            pair.local.mkdir(parents=True, exist_ok=True)
            command += [f"{self.host}:{target}/", f"{pair.local}/"]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            raise ToolError("The sync did not finish within 15 minutes.") from None
        if done.returncode != 0:
            raise ToolError(f"rsync failed (exit code {done.returncode}):\n{done.stderr.strip()[-1500:]}")
        files = [line for line in done.stdout.splitlines() if line and not line.endswith("/")]
        return _sync_report(pair, target, files, preview)


def _sync_report(pair: SyncPair, target: str, files: list[str], preview: bool) -> str:
    arrow = f"{pair.local} -> {target}" if pair.direction == "push" else f"{target} -> {pair.local}"
    if not files:
        return f"Already up to date ({arrow})."
    shown = "\n".join(f"  {f}" for f in files[:40]) + (f"\n  ... and {len(files) - 40} more" if len(files) > 40 else "")
    verb = "Would copy" if preview else "Copied"
    return f"{verb} {len(files)} changed file(s), {arrow}:\n{shown}"


@dataclass
class _MockJob:
    id: str
    name: str
    script: str
    submitted: float
    cancelled: bool = False


_MOCK_MODULES = {
    "python": ["Python/3.10.8", "Python/3.11.3", "Python/3.11.5", "Python/3.12.3"],
    "gcc": ["GCC/12.3.0", "GCC/13.2.0"],
    "pytorch": ["PyTorch/2.1.2-CUDA-12.1.1", "PyTorch/2.7.1-CUDA-12.6.0"],
}


class MockBackend:
    """A pretend cluster: each job waits `pending_s` seconds, runs `run_s` seconds, then completes."""

    def __init__(self, pending_s: float = 8.0, run_s: float = 20.0):
        self.pending_s, self.run_s = pending_s, run_s
        self.jobs: dict[str, _MockJob] = {}
        self.files: dict[str, str] = {}
        self._ids = itertools.count(9_100_001)
        self.logged_in = True

    def connected(self) -> bool:
        return self.logged_in

    def session_age(self) -> str | None:
        return "00:05:00" if self.logged_in else None

    def end_session(self) -> str:
        if not self.logged_in:
            return "There was no open login session (simulated cluster); nothing to close."
        self.logged_in = False
        return "Closed the shared login (simulated cluster). To use it again, the user runs `ssh grace`."

    def _state(self, job: _MockJob) -> str:
        if job.cancelled:
            return "CANCELLED"
        age = time.time() - job.submitted
        if age < self.pending_s:
            return "PENDING"
        return "RUNNING" if age < self.pending_s + self.run_s else "COMPLETED"

    def _require_login(self) -> None:
        if not self.logged_in:
            raise ToolError(NOT_CONNECTED.format(host="grace (simulated)"))

    def _job(self, job_id: str) -> _MockJob:
        self._require_login()
        if job_id not in self.jobs:
            raise ToolError(NOT_OURS.format(job_id=job_id))
        return self.jobs[job_id]

    def cluster_status(self) -> str:
        return (
            "(simulated cluster)\nPARTITION AVAIL  TIMELIMIT   NODES(A/I/O/T)\n"
            "short*       up    2:00:00   775/9/16/800\n"
            "gpu          up 4-00:00:00    109/7/1/117"
        )

    def my_jobs(self) -> str:
        self._require_login()
        rows = [
            f"{j.id:>10} {'short':>10} {j.name[:20]:>20} {self._state(j):>9}"
            for j in self.jobs.values()
            if self._state(j) in ("PENDING", "RUNNING")
        ]
        header = f"(simulated cluster)\n{'JOBID':>10} {'PARTITION':>10} {'NAME':>20} {'STATE':>9}"
        return "\n".join([header, *rows]) if rows else header + "\n(no jobs from this server are queued or running)"

    def submit(self, script: str, name: str) -> str:
        self._require_login()
        job_id = str(next(self._ids))
        self.jobs[job_id] = _MockJob(job_id, name, script, time.time())
        return job_id

    def job_details(self, job_id: str) -> str:
        job = self._job(job_id)
        state = self._state(job)
        exit_code = "0:0" if state == "COMPLETED" else "0:15" if state == "CANCELLED" else ""
        return (
            f"(simulated cluster)\nJobID      JobName                    State      ExitCode\n"
            f"{job.id:<10} {job.name:<26} {state:<10} {exit_code}"
        )

    def job_output(self, job_id: str, lines: int) -> str:
        job = self._job(job_id)
        if self._state(job) == "PENDING":
            return "No output yet (the job may still be waiting in the queue)."
        commands = [l for l in job.script.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        out = ["(simulated cluster: commands were not really executed)", "host=mock-c001"]
        out += [f"$ {c}" for c in commands]
        if any("monte_carlo_pi" in c for c in commands) and self._state(job) == "COMPLETED":
            out.append("pi ~ 3.141672  (error 7.94e-05)  [simulated]")
        return "\n".join(out[-lines:])

    def cancel(self, job_id: str) -> str:
        self._job(job_id).cancelled = True
        return f"Cancel request sent for job {job_id} (simulated cluster)."

    def find_software(self, name: str) -> str:
        versions = _MOCK_MODULES.get(name.split("/")[0].lower())
        if not versions:
            return f"(simulated cluster) Unable to find: {name}"
        if "/" in name:
            return f"(simulated cluster) To load {name}, first load: GCCcore/12.3.0"
        return "(simulated cluster)\n" + "\n".join(versions)

    def quota(self) -> str:
        return "(simulated cluster)\n/home     2.1G of 10G\n/scratch  37G of 1T"

    def list_files(self) -> str:
        return "(simulated cluster)\n" + ("\n".join(sorted(self.files)) or "(empty)")

    def copy_to_cluster(self, local: Path) -> str:
        self.files[local.name] = local.read_text()
        return f"/scratch/user/demo/mcp_jobs/{local.name}"

    def sync(self, pair: SyncPair, preview: bool) -> str:
        target = f"/scratch/user/demo/{pair.remote}"
        files = []
        if pair.direction == "push" and pair.local.is_dir():
            for path in sorted(pair.local.rglob("*")):
                relative = path.relative_to(pair.local)
                if path.is_file() and not any(part in pair.exclude for part in relative.parts):
                    files.append(str(relative))
        return "(simulated cluster) " + _sync_report(pair, target, files, preview)
