"""Safety limits checked before any job is submitted.

Cluster time is real money, so the server, not the AI, has the last word on
partition, run time, nodes and GPUs. A rejected script comes back with a list
of what to fix, which the AI can read and correct.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from .config import Config

_SHORT_FLAGS = {"-t": "time", "-p": "partition", "-N": "nodes", "-G": "gpus", "-J": "job-name", "-a": "array"}


def sbatch_options(script: str) -> dict[str, str]:
    """Collect the '#SBATCH' options of a job script, e.g. {'time': '00:10:00', 'partition': 'short'}."""
    options: dict[str, str] = {}
    for line in script.splitlines():
        if not line.startswith("#SBATCH"):
            continue
        words = shlex.split(line[len("#SBATCH"):].split(" #")[0])
        i = 0
        while i < len(words):
            word = words[i]
            if word.startswith("--"):
                key, _, value = word[2:].partition("=")
                if not value and i + 1 < len(words) and not words[i + 1].startswith("-"):
                    value, i = words[i + 1], i + 1
                options[key] = value
            elif word[:2] in _SHORT_FLAGS:
                value = word[2:]
                if not value and i + 1 < len(words):
                    value, i = words[i + 1], i + 1
                options[_SHORT_FLAGS[word[:2]]] = value
            i += 1
    return options


def slurm_minutes(value: str) -> float:
    """Slurm time formats: M, M:S, H:M:S, D-H, D-H:M, D-H:M:S."""
    if value.upper() in ("UNLIMITED", "INFINITE"):
        return float("inf")
    days, _, clock = value.rpartition("-")
    parts = [int(p) for p in clock.split(":")]
    if days:
        hours, minutes, seconds = (parts + [0, 0])[:3]
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, (minutes, seconds) = 0, parts
    else:
        hours, minutes, seconds = 0, parts[0], 0
    return int(days or 0) * 1440 + hours * 60 + minutes + seconds / 60


def requested_gpus(options: dict[str, str]) -> int:
    total = 0
    for key in ("gres", "gpus", "gpus-per-node"):
        for item in options.get(key, "").split(","):
            if key == "gres" and not item.startswith("gpu"):
                continue
            match = re.search(r"(\d+)$", item)
            if match:
                total += int(match.group(1))
            elif item.startswith("gpu"):
                total += 1
    return total


ALLOWED_COMMANDS = {"module", "cd", "python", "python3", "srun", "echo", "hostname", "date", "nvidia-smi", "export"}
_FORBIDDEN = (";", "&", "|", "`", "$(", ">", "<")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def check_commands(script: str, programs: set[str], jobs_dir: str) -> list[str]:
    """The commands a job may run: load modules, enter the job folder, run one of the example
    programs, and print information. Returns the example programs the script runs.

    This is what makes the server safe to hand out: a job cannot delete, move or send files,
    because no command that could do so is accepted."""
    problems, used = [], []
    job_folders = {f"$SCRATCH/{jobs_dir}", f"${{SCRATCH}}/{jobs_dir}"}
    for number, line in enumerate(script.splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        where = f"line {number} ({text[:40]})"
        if any(token in text for token in _FORBIDDEN):
            problems.append(f"{where}: pipes, redirection, ';', '&', backticks and '$(...)' are not allowed.")
            continue
        try:
            words = shlex.split(text)
        except ValueError:
            problems.append(f"{where}: unbalanced quotes.")
            continue
        if words[0] == "srun":
            words = [w for w in words[1:] if not w.startswith("-")] or ["srun"]
        command, args = words[0], words[1:]
        if command not in ALLOWED_COMMANDS:
            problems.append(f"{where}: '{command}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}.")
        elif command == "module" and (not args or args[0] not in ("purge", "load", "list")):
            problems.append(f"{where}: only 'module purge', 'module load ...' and 'module list' are allowed.")
        elif command == "cd" and (len(args) != 1 or args[0].rstrip("/") not in job_folders):
            problems.append(f'{where}: the only folder a job may enter is "$SCRATCH/{jobs_dir}".')
        elif command in ("python", "python3"):
            files = [a for a in args if a != "-u"]
            name = Path(files[0]).name if files else ""
            if not files or files[0].startswith("-") or name not in programs:
                problems.append(
                    f"{where}: python may only run one of the example programs: {', '.join(sorted(programs))} "
                    "(no -c or -m)."
                )
            else:
                used.append(name)
        elif command == "export" and not all(_ENV_ASSIGNMENT.match(a) for a in args):
            problems.append(f"{where}: export must look like 'export NAME=value'.")
    if problems:
        raise ToolError("Job NOT submitted. Please fix:\n- " + "\n- ".join(problems))
    return used


def check_job_script(script: str, config: Config) -> None:
    """Raise ToolError listing every problem, or return quietly if the script may be submitted."""
    options = sbatch_options(script)
    problems = []
    if "array" in options:
        problems.append("Job arrays are not allowed here; submit one job at a time.")
    if not script.startswith("#!"):
        problems.append("The script must start with a shebang line such as #!/bin/bash.")
    if "time" not in options:
        problems.append(f"Set a run-time limit, e.g. '#SBATCH --time=00:10:00' (at most {config.max_minutes} minutes).")
    else:
        try:
            if slurm_minutes(options["time"]) > config.max_minutes:
                problems.append(f"--time={options['time']} is longer than the allowed {config.max_minutes} minutes.")
        except ValueError:
            problems.append(f"Could not read --time={options['time']}; use HH:MM:SS.")
    partition = options.get("partition")
    if partition and config.partitions and partition not in config.partitions:
        problems.append(f"Partition '{partition}' is not allowed here; use one of: {', '.join(config.partitions)}.")
    nodes = options.get("nodes", "1").split("-")[-1]
    if nodes.isdigit() and int(nodes) > config.max_nodes:
        problems.append(f"At most {config.max_nodes} node(s) may be requested.")
    if requested_gpus(options) > config.max_gpus:
        problems.append(f"At most {config.max_gpus} GPU(s) may be requested.")
    if problems:
        raise ToolError("Job NOT submitted. Please fix:\n- " + "\n- ".join(problems))
