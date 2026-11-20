#!/bin/bash
#SBATCH --job-name=report
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-logs/%x-%j.log

pixi run python analysis/phase2.py --from_out out-phase2-cold --output_dir results/phase2-cold
