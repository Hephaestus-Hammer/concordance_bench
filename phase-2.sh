#!/bin/bash
#SBATCH --job-name=phase2
#SBATCH --output=slurm-logs/%x-%j.log
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
# Phase 2: the three slices, the five pipelines, then the tables and the report.
# Run from the repository root:  sbatch run_phase2.sbatch
set -euo pipefail

for s in pca knn cluster; do
    pixi run ob run benchmark-phase2.yaml --filter filters/phase2/slice-$s.yaml \
        --out-dir out-phase2-cold --cores 8 --continue-on-error
done
bash scripts/run_pipelines.sh out-phase2-cold

pixi run phase2
pixi run report2
