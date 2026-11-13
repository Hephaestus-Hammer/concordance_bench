#!/bin/bash
# Run the Phase 2 pipelines slice: every filter in filters/phase2/pipelines/ (5 named pipelines x
# 5 matched seeds), one ob run each, into one output folder, so jobs the pipelines share (the
# exact PCA and kNN) run once. Run from the repository root, on a GPU host (all-gpu, hybrid):
#
#   bash scripts/run_pipelines.sh                       # into out-phase2/
#   bash scripts/run_pipelines.sh out-phase2-rep1       # a same-seed replicate folder
#   PIPELINES="baseline tuned-cpu" bash scripts/run_pipelines.sh   # a subset (CPU host)
#
# Under Slurm: sbatch --gres=gpu:1 --cpus-per-task=8 --mem=32G scripts/run_pipelines.sh
#SBATCH --job-name=phase2-pipelines
#SBATCH --output=slurm-logs/%x-%j.log
set -euo pipefail
out="${1:-out-phase2}"
cores="${SLURM_CPUS_PER_TASK:-8}"
names="${PIPELINES:-baseline scanpy-defaults tuned-cpu all-gpu hybrid}"
for name in $names; do
    for f in filters/phase2/pipelines/"$name"-seed*.yaml; do
        echo "== $f"
        pixi run ob run benchmark-phase2.yaml --filter "$f" --out-dir "$out" --cores "$cores" --continue-on-error
    done
done
