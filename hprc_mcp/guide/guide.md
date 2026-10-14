# Working on {cluster} (Texas A&M HPRC): house rules

- **Login nodes are for editing and submitting only.** All real work runs as a Slurm batch job.
- **Where files go**
  - `$HOME` (`/home/<user>`): small space for code and settings: 10 GB and 10,000 files.
  - `$SCRATCH` (`/scratch/user/<user>`): working space for data, job scripts and results:
    1 TB and 250,000 files. It is not backed up.
  - Use the `check_quota` tool for the user's current usage.
- **Partitions (queues)**: `short` (default, up to 2 hours), `medium` (1 day), `long` (7 days),
  `gpu` (4 days; GPU types `a100`, `rtx`, `t4`, requested as `--gres=gpu:a100:1`),
  `bigmem` (2 days). Use `cluster_status` for live availability.
- **This server's conventions**
  - Job scripts are saved in `$SCRATCH/{jobs_dir}/` and run from there. The example programs a script
    runs are copied into that folder automatically by `submit_job`.
  - Each job's output goes to `$SCRATCH/{jobs_dir}/logs/<jobid>.out`. The server creates that folder
    and sets `--output`/`--error` itself, so job scripts do not need them.
- **Software comes from environment modules.** Never guess module names or versions: use
  `find_software`. A full name such as `Python/3.11.5` shows which modules must be loaded first
  (for example `module load GCCcore/13.2.0 Python/3.11.5`).
  Start the commands in a job script with `module purge`, then `module load` what is needed.
- **Every job script** starts with `#!/bin/bash` and sets `--job-name`, `--time`, `--ntasks`,
  `--cpus-per-task` and `--mem`. Use `$SLURM_CPUS_PER_TASK` instead of hard-coding the core count.
- **Commands a job script may contain** (checked before submission): {commands}.
  Enter the job folder with `cd "$SCRATCH/{jobs_dir}"` and run a program by its file name,
  e.g. `python monte_carlo_pi.py --workers "$SLURM_CPUS_PER_TASK"`.
- **Assume compute nodes have no internet access**: copy inputs to the cluster before the job starts.
- **Limits enforced by this server**: {limits}.
