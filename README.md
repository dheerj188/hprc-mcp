# hprc-mcp: let an AI run jobs on TAMU HPRC, safely

An [MCP](https://modelcontextprotocol.io) server that gives an AI assistant (Claude Code, Claude
Desktop, or any MCP app) the context and tools to work on the **Grace** cluster with your own account:
real module versions, house rules, working sample job scripts, and tools to submit, track and
cancel jobs. It accompanies the ENG 689 tutorial on MCP ([TUTORIAL.md](TUTORIAL.md)).

## Quick start (on your laptop)

```bash
git clone https://github.com/dheerj188/hprc-mcp.git && cd hprc-mcp
./setup.sh <NetID>     # one time: installs the server on this laptop, adds Grace to ~/.ssh/config,
                       # registers it with Claude Desktop / Claude Code
ssh grace              # password + Duo once, then type exit (the login stays shared in the background)
```

Then open **Claude Desktop** (quit and reopen it once; use a normal chat and switch on `hprc`), or run
**`claude`** in this folder. **When you are done**, tell Claude *"I'm done, end the session"* or run
`ssh -O exit grace`; closing the terminal does not end it, but it closes itself after 1 hour without use. **Nothing is installed on Grace**: the server runs on your laptop and sends
Slurm commands through your SSH login. The only files it creates on Grace are job scripts and logs in
`$SCRATCH/mcp_jobs`.

You need an HPRC account, macOS or Linux (on Windows, use WSL and Claude Code inside it, because Windows'
own SSH cannot share a login), and Claude Desktop or Claude Code (Claude Code needs a Pro/Max plan or an
API key).

## Try it

- *Can you reach the cluster?*
- *Run examples/monte_carlo_pi.py with 4 cores for 10 minutes and tell me the result.*
- *How is my job doing?* then *Show me its output.*
- *Which launch angle goes farthest at 40 m/s? Use examples/projectile_drag.py.*
- *Write and submit a GPU job that runs examples/gpu_check.py.*

## What the AI gets

| MCP building block | In this server |
|---|---|
| **Prompts**: how we do things here | `write_job_script`, `debug_failed_job` |
| **Resources**: what we have | house rules (`hprc://guide`), sample CPU/GPU scripts, live module versions |
| **Tools**: what it can do | `connection_status`, `end_session`, `hprc_guide`, `find_software`, `cluster_status`, `check_quota`, `list_files`, `copy_to_cluster`, `submit_job`, `my_jobs`, `job_details`, `job_output`, `cancel_job` |

## Safety

- **No tool deletes, moves or edits files, and there is no shell tool.**
- **Job scripts are checked before submission.** They may only load modules, `cd "$SCRATCH/mcp_jobs"`,
  run a program from `examples/`, and use `echo`, `hostname`, `date`, `nvidia-smi`, `export`. Pipes,
  redirection, `;`, `&&` and `$(...)` are rejected, as are jobs over the limits in
  [config/hprc_mcp.toml](config/hprc_mcp.toml) (partitions `short`/`gpu`, 60 min, 1 node, 1 GPU, no arrays).
- **The AI only sees and cancels jobs it submitted** (those running in `$SCRATCH/mcp_jobs`), never your other work.
- **In this folder, Claude Code's own shell, file-editing and web tools are switched off**
  ([.claude/settings.json](.claude/settings.json)); submitting or cancelling a job always asks you first.
- No passwords or keys are stored: the server reuses your own `ssh grace` login and never sees your
  password. Everything runs as you, with your normal permissions. Whatever the AI reads (job output,
  the guide) is sent to the AI provider as part of the conversation.
- These are guardrails for a shared teaching repo, not a sandbox: keep the defaults when you share it.

## Add your own program

Put a `.py` file in [examples/](examples/). The AI can now run it with the same checks. Programs that
need packages should load them as modules (see `hprc_guide`).

## Without an AI

`uv run python client/mini_client.py` lists the server's menu and calls one tool on a simulated
cluster (add `--real` to use Grace). `uv run python scripts/live_check.py --submit` runs a full test job.

## Layout

```
hprc_mcp/server.py   prompts, resources and tools (start here)
hprc_mcp/limits.py   safety checks run before every submission
hprc_mcp/backend.py  how commands reach Slurm: over your ssh login, or a simulated cluster
hprc_mcp/guide/      house rules and sample job scripts the AI receives
examples/            the programs jobs may run
setup.sh             one-time setup on your laptop
```
