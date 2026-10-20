#!/bin/bash
# Run the benchmark inside one Slurm allocation: Snakemake schedules every job within it.
#
#   sbatch run.sbatch                              # whole plan (rapids skipped without a GPU)
#   sbatch run.sbatch filters/smoke.yaml           # a filter
#   sbatch --gres=gpu:1 run.sbatch                 # with a GPU: adds --with-capability gpu
#   sbatch run.sbatch filters/smoke.yaml --dry     # extra arguments go to `ob run`
#
# Needs `conda` on PATH (Snakemake builds the module environments with it), e.g. via
# `module load` on the cluster, and network access for the data stage (Hugging Face).
#SBATCH --job-name=concordance-bench
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=%x-%j.log

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-.}"

command -v conda >/dev/null || { echo "error: conda not on PATH (needed for snakemake --use-conda)" >&2; exit 1; }

args=(--cores "${SLURM_CPUS_PER_TASK:-1}" --continue-on-error)
if [[ $# -gt 0 && $1 == *.yaml ]]; then args+=(--filter "$1"); shift; fi
if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then args+=(--with-capability gpu); fi

# Keep Snakemake's per-rule mem_mb within the allocation (SLURM_MEM_PER_NODE is in MB).
snakemake_args=()
if [[ -n "${SLURM_MEM_PER_NODE:-}" ]]; then snakemake_args+=(-- --resources "mem_mb=$SLURM_MEM_PER_NODE"); fi

pixi run --frozen ob run benchmark.yaml "${args[@]}" "$@" "${snakemake_args[@]}"
