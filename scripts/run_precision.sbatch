#!/bin/bash
#SBATCH --job-name=precision
#SBATCH --output=slurm-logs/%x-%j.log
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=1-00:00:00
# float32 against float64 PCA (analysis/precision.py): the replicate folders of the two
# scripts/run_phase2.sbatch runs on one hardware, compared run by run, into
# results/precision_<hardware>/ (TSVs and precision.html). No GPU needed.
#
#   sbatch scripts/run_precision.sbatch                       # the one hardware tag with both precisions
#   HW=A100-SXM4-80GB_8core sbatch scripts/run_precision.sbatch
#   sbatch --dependency=afterok:<float64 job>:<float32 job> scripts/run_precision.sbatch
#
# Run from the repository root.
set -euo pipefail
shopt -s nullglob

if [[ -z "${HW:-}" ]]; then
    tags=()
    for d in out-phase2_float64_*_rep1; do
        t="${d#out-phase2_float64_}"; t="${t%_rep1}"
        [[ -d "out-phase2_float32_${t}_rep1" ]] && tags+=("$t")
    done
    if [[ ${#tags[@]} -ne 1 ]]; then
        echo "found ${#tags[@]} hardware tags with both precisions (${tags[*]:-none}): set HW=<tag>" >&2
        exit 2
    fi
    HW="${tags[0]}"
fi
f64=(out-phase2_float64_"${HW}"_rep*)
f32=(out-phase2_float32_"${HW}"_rep*)
[[ ${#f64[@]} -gt 0 && ${#f32[@]} -gt 0 ]] || { echo "no float64 or no float32 folders for $HW" >&2; exit 2; }
echo "float64: ${f64[*]}"
echo "float32: ${f32[*]}"
pixi run python analysis/precision.py --float64 "${f64[@]}" --float32 "${f32[@]}" --output_dir "results/precision_${HW}"
