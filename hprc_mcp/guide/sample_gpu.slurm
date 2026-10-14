#!/bin/bash
#SBATCH --job-name=sample_gpu
#SBATCH --time=00:10:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --partition=gpu
#SBATCH --gres=gpu:a100:1
# (Grace GPU types: a100, rtx, t4)

module purge
module load GCC/12.3.0 OpenMPI/4.1.5 PyTorch/2.1.2-CUDA-12.1.1

cd "$SCRATCH/mcp_jobs"
nvidia-smi
python gpu_check.py
