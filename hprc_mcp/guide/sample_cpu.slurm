#!/bin/bash
#SBATCH --job-name=sample_cpu
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G

module purge
module load GCCcore/12.3.0 Python/3.11.3

cd "$SCRATCH/mcp_jobs"
python monte_carlo_pi.py --workers "$SLURM_CPUS_PER_TASK"
