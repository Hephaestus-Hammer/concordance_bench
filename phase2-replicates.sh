#!/bin/bash
#SBATCH --job-name=phase2-reps
#SBATCH --output=slurm-logs/%x-%j.log
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=4-00:00:00
set -euo pipefail

for out in out-phase2-cold out-phase2-cold-rep1 out-phase2-cold-rep2; do
    for s in pca knn cluster; do
        pixi run ob run benchmark-phase2.yaml --filter filters/phase2/slice-$s.yaml \
            --out-dir "$out" --cores 8 --continue-on-error
    done
    bash scripts/run_pipelines.sh "$out"
done

pixi run python analysis/phase2.py \
    --from_out out-phase2-cold out-phase2-cold-rep1 out-phase2-cold-rep2 \
    --output_dir results/phase2-cold-reps
