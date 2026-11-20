#!/bin/bash
#SBATCH --job-name=report
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-logs/%x-%j.log

pixi run python analysis/phase2.py --from_out out-phase2_float64_L4_8core_rep* --output_dir results/phase2_float64_L4_8core
