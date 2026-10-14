"""Tests: a real MCP client talks to the server, which runs on a simulated cluster."""

import asyncio
import subprocess

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from hprc_mcp.backend import LocalBackend, MockBackend, SSHBackend
from hprc_mcp.config import REPO, Config, SyncPair
from hprc_mcp.limits import check_commands, check_job_script, requested_gpus, sbatch_options, slurm_minutes
from hprc_mcp.server import build_server

GOOD_SCRIPT = """#!/bin/bash
#SBATCH --job-name=pi_demo
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --partition=short
module purge
module load GCCcore/12.3.0 Python/3.11.3
cd "$SCRATCH/mcp_jobs"
python monte_carlo_pi.py --workers "$SLURM_CPUS_PER_TASK"
"""
PROGRAMS = {"monte_carlo_pi.py", "gpu_check.py", "projectile_drag.py"}
EXPECTED_TOOLS = {
    "connection_status", "end_session", "hprc_guide", "find_software", "cluster_status", "check_quota", "list_files",
    "copy_to_cluster", "submit_job", "my_jobs", "job_details", "job_output", "cancel_job",
}


def run(coro):
    return asyncio.run(coro)


def text(result) -> str:
    return "\n".join(block.text for block in result.content)


async def call(server, tool, args=None):
    async with Client(server) as client:
        return await client.call_tool(tool, args or {})


def test_menu_is_exactly_the_safe_tool_set():
    async def main():
        async with Client(build_server(MockBackend(), Config())) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            resources = {str(r.uri) for r in (await client.list_resources()).resources}
            prompts = {p.name for p in (await client.list_prompts()).prompts}
            return tools, resources, prompts

    tools, resources, prompts = run(main())
    assert tools == EXPECTED_TOOLS  # nothing that deletes, edits or runs arbitrary commands
    assert {"hprc://guide", "hprc://samples/cpu", "hprc://samples/gpu"} <= resources
    assert {"write_job_script", "debug_failed_job"} <= prompts


def test_submit_copies_the_program_tracks_and_reads_output():
    backend = MockBackend(pending_s=0, run_s=0)

    async def main():
        async with Client(build_server(backend, Config())) as client:
            submitted = await client.call_tool("submit_job", {"script": GOOD_SCRIPT, "name": "pi_demo"})
            job_id = text(submitted).split()[2]
            details = await client.call_tool("job_details", {"job_id": job_id})
            output = await client.call_tool("job_output", {"job_id": job_id})
            return submitted, details, output

    submitted, details, output = run(main())
    assert not submitted.is_error and "Submitted job" in text(submitted)
    assert "monte_carlo_pi.py" in backend.files  # copied automatically
    assert "COMPLETED" in text(details) and "pi ~" in text(output)


@pytest.mark.parametrize("line, reason", [
    ("rm -rf $SCRATCH", "'rm' is not allowed"),
    ("python monte_carlo_pi.py > out.txt", "redirection"),
    ("python -c 'import shutil'", "example programs"),
    ("python ../secret.py", "example programs"),
    ("cd $HOME", "only folder"),
    ("curl https://example.com", "'curl' is not allowed"),
    ("module use /tmp", "module purge"),
    ("echo hi; rm x", "pipes"),
    ("echo $(whoami)", "pipes"),
])
def test_dangerous_job_commands_are_rejected(line, reason):
    with pytest.raises(ToolError, match=reason):
        check_commands(GOOD_SCRIPT + line + "\n", PROGRAMS, "mcp_jobs")


def test_allowed_commands_pass_and_report_programs():
    script = GOOD_SCRIPT + "srun python projectile_drag.py --speed 40\necho done\nhostname\nexport OMP_NUM_THREADS=4\n"
    assert check_commands(script, PROGRAMS, "mcp_jobs") == ["monte_carlo_pi.py", "projectile_drag.py"]


def test_limits_reject_with_reasons_the_ai_can_act_on():
    bad = GOOD_SCRIPT.replace("00:10:00", "05:00:00").replace("short", "long")
    bad += "#SBATCH --gres=gpu:a100:2\n#SBATCH --array=1-100\n"
    result = run(call(build_server(MockBackend(), Config()), "submit_job", {"script": bad, "name": "too_big"}))
    message = text(result)
    assert result.is_error and "Job NOT submitted" in message and "60 minutes" in message
    assert "Partition 'long'" in message and "GPU" in message and "arrays" in message


def test_copy_only_accepts_example_programs():
    server = build_server(MockBackend(), Config())
    for name in ("../pyproject.toml", "/etc/passwd", "examples/../README.md"):
        result = run(call(server, "copy_to_cluster", {"filename": name}))
        assert result.is_error and "not one of the example programs" in text(result)
    assert not run(call(server, "copy_to_cluster", {"filename": "examples/monte_carlo_pi.py"})).is_error


def test_resources_and_prompts_carry_real_context():
    async def main():
        async with Client(build_server(MockBackend(), Config())) as client:
            guide = await client.read_resource("hprc://guide")
            prompt = await client.get_prompt("write_job_script", {"task": "estimate pi", "cores": "4"})
            return guide.contents[0].text, prompt.messages[0].content.text

    guide, prompt = run(main())
    assert "Grace" in guide and "{" not in guide and "monte_carlo_pi.py" in guide
    assert "estimate pi" in prompt and "#SBATCH" in prompt and "find_software" in prompt


def test_slurm_parsing_helpers():
    assert slurm_minutes("10") == 10
    assert slurm_minutes("01:30:00") == 90
    assert slurm_minutes("1-02") == 1560
    assert slurm_minutes("2:30") == 2.5
    options = sbatch_options("#SBATCH -t 15 -p gpu\n#SBATCH --gres=gpu:a100:1\n#SBATCH --nodes 1\n")
    assert options == {"time": "15", "partition": "gpu", "gres": "gpu:a100:1", "nodes": "1"}
    assert requested_gpus(options) == 1
    check_job_script(GOOD_SCRIPT, Config())


def test_only_jobs_from_this_server_are_visible(monkeypatch):
    backend = LocalBackend("mcp_jobs")
    monkeypatch.setattr(backend, "connected", lambda: True)
    replies = {
        'echo "$SCRATCH"/mcp_jobs': "/scratch/user/me/mcp_jobs",
        "sacct -j 111 -X -n -P --format=WorkDir": "/scratch/user/me/mcp_jobs",
        "sacct -j 222 -X -n -P --format=WorkDir": "/scratch/user/me/my_research",
        'squeue -u "$USER" -h -o "%i|%P|%j|%T|%M|%l|%R|%Z"':
            "111|short|pi_demo|RUNNING|0:10|10:00|c001|/scratch/user/me/mcp_jobs\n"
            "222|gpu|thesis_run|RUNNING|5:00:00|2-00:00:00|g001|/scratch/user/me/my_research",
    }
    monkeypatch.setattr(backend, "run", lambda command, *a, **k: replies.get(command, "ok"))
    jobs = backend.my_jobs()
    assert "pi_demo" in jobs and "thesis_run" not in jobs
    with pytest.raises(ToolError, match="not submitted through this server"):
        backend.cancel("222")
    assert "Cancel request sent" in backend.cancel("111")


def test_without_slurm_or_login_every_tool_says_no_quickly(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ToolError, match="Not connected"):
        LocalBackend("mcp_jobs").my_jobs()

    calls = []

    def fake_run(command, *args, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 255, "", "Control socket connect: No such file or directory")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = SSHBackend("grace", "~/.ssh/cm-%C", "mcp_jobs")
    with pytest.raises(ToolError, match="Not connected to grace.*stop"):
        backend.my_jobs()
    assert all("-O" in c for c in calls)  # only the local session check ran, never a login attempt
    result = run(call(build_server(backend, Config()), "connection_status"))
    assert not result.is_error and text(result).startswith("Not connected to Grace")


def test_sync_folder_appears_only_when_configured():
    config = Config(syncs={"examples": SyncPair(REPO / "examples", "mcp_jobs", "push")})

    async def main():
        async with Client(build_server(MockBackend(), config)) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "sync_folder")
            ok = await client.call_tool("sync_folder", {"name": "examples", "preview": True})
            unknown = await client.call_tool("sync_folder", {"name": "home"})
            return tool, ok, unknown

    tool, ok, unknown = run(main())
    assert "'examples' (push" in tool.description
    assert "Would copy" in text(ok) and unknown.is_error


def test_repo_config_parses_and_rejects_unsafe_sync_paths():
    from hprc_mcp.config import _sync_pair, load_config

    assert load_config().partitions
    for remote in ("../etc", "/abs/path", "a/../b", "has space"):
        with pytest.raises(ValueError):
            _sync_pair("bad", {"local": "examples", "remote": remote})


def test_end_session_closes_the_login_and_tools_then_say_no():
    backend = MockBackend()

    async def main():
        async with Client(build_server(backend, Config())) as client:
            before = await client.call_tool("connection_status", {})
            empty = await client.call_tool("my_jobs", {})
            closed = await client.call_tool("end_session", {})
            after = await client.call_tool("connection_status", {})
            jobs = await client.call_tool("my_jobs", {})
            return before, empty, closed, after, jobs

    before, empty, closed, after, jobs = run(main())
    assert "open for" in text(before) and "end_session" in text(before)
    assert "offer to close the login" in text(empty)  # reminder when nothing is running
    assert "Closed the shared login" in text(closed)
    assert text(after).startswith("Not connected") and jobs.is_error


def test_ssh_end_session_sends_exit_to_the_shared_login(monkeypatch):
    state = {"open": True, "calls": []}

    def fake_run(command, *args, **kwargs):
        state["calls"].append(command)
        if "-O" in command:
            action = command[command.index("-O") + 1]
            if action == "exit":
                state["open"] = False
            return subprocess.CompletedProcess(command, 0 if state["open"] else 255, "", "Master running (pid=4242)")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    message = SSHBackend("grace", "~/.ssh/cm-%C", "mcp_jobs").end_session()
    assert "Closed the shared login to grace" in message
    assert any(c[-3:] == ["-O", "exit", "grace"] for c in state["calls"])


def test_on_a_login_node_there_is_no_session_to_end():
    import asyncio as _asyncio

    async def main():
        async with Client(build_server(LocalBackend("mcp_jobs"), Config())) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert "end_session" not in _asyncio.run(main())
