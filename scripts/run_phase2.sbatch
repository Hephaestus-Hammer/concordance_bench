#!/bin/bash
#SBATCH --job-name=phase2
#SBATCH --output=slurm-logs/%x-%j.log
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
# One full Phase 2 run (the three slices and the five pipelines), then its tables and report.
# The output folder is named after the PCA precision and the hardware the job landed on:
#   out-phase2_<precision>_<GPU>_<N>core      e.g. out-phase2_float32_A100-SXM4-80GB_8core
# and the tables and report go to results/phase2_<same>.
#
#   sbatch scripts/run_phase2.sbatch                       # float64: the plan as it is
#   PRECISION=float32 sbatch scripts/run_phase2.sbatch     # every PCA module computes in float32
#   REP=rep1 PRECISION=float32 sbatch scripts/run_phase2.sbatch   # a same-seed replicate folder
#
# float32 writes benchmark-phase2-float32.yaml (the plan with every PCA `dtype: float64` set to
# float32) and its own filters in filters/phase2-float32/, so the two precisions never share a
# folder, a filter or a report. kNN and Leiden keep their own precision (see docs/phase2-plan.md).
# Run from the repository root.
set -euo pipefail

precision="${PRECISION:-float64}"
case "$precision" in
    float64) plan=benchmark-phase2.yaml; filters=filters/phase2 ;;
    float32)
        plan=benchmark-phase2-float32.yaml; filters=filters/phase2-float32
        sed 's/dtype: float64/dtype: float32/g' benchmark-phase2.yaml > "$plan"
        grep -q "dtype: float32" "$plan"
        pixi run python scripts/make_filters.py --plan "$plan" --out "$filters"
        ;;
    *) echo "PRECISION must be float64 or float32, not $precision" >&2; exit 2 ;;
esac

tag="${precision}_$(bash scripts/hw_tag.sh)${REP:+_$REP}"
out="out-phase2_${tag}"
res="results/phase2_${tag}"
cores="${SLURM_CPUS_PER_TASK:-8}"
echo "plan $plan, filters $filters, output $out, results $res"

for s in pca knn cluster; do
    pixi run ob run "$plan" --filter "$filters/slice-$s.yaml" --out-dir "$out" --cores "$cores" --continue-on-error
done
PLAN="$plan" FILTERS="$filters" bash scripts/run_pipelines.sh "$out"

# tables, then the report (phase2.py renders it at the end)
pixi run python analysis/phase2.py --from_out "$out" --output_dir "$res"
