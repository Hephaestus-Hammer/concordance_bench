#!/bin/bash
#SBATCH --job-name=phase2
#SBATCH --output=slurm-logs/%x-%j.log
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=2-00:00:00
# One Phase 2 run (the three slices and the five pipelines), then its tables and report.
# The output folder is named after the variant and the hardware the job landed on:
#   out-phase2_<precision>[_<format>]_<GPU>_<N>core[_<rep>]   e.g. out-phase2_float32_A100-SXM4-80GB_8core
# and the tables and report go to results/phase2_<same>.
#
#   sbatch scripts/run_phase2.sbatch                          # float64, omni files: the plan as it is
#   PRECISION=float32 sbatch scripts/run_phase2.sbatch        # every PCA module computes in float32
#   FORMAT=h5ad-dense SLICES=pca PIPELINES=none sbatch ...    # file format: only PCA reads the matrix
#   REP=rep1 PRECISION=float32 sbatch scripts/run_phase2.sbatch   # a same-seed replicate folder
#
# PRECISION  float64 (default) | float32: every PCA `dtype: float64` in the plan set to float32.
# FORMAT     omni (default) | 10x | h5ad | h5ad-dense: the input modules write the matrix in that
#            format (modules/matrix_formats.py); needs the input, scanpy-fork and rapids commits
#            in the plan to be ones that write and read it.
# SLICES     the slices to run, default "pca knn cluster".  PIPELINES: names, or "none".
# Anything but the defaults writes its own plan (benchmark-phase2-<variant>.yaml) and filters
# (filters/phase2-<variant>/), so variants never share a folder, a filter or a report.
# Run from the repository root.
set -euo pipefail

precision="${PRECISION:-float64}"
format="${FORMAT:-omni}"
case "$precision" in float64|float32) ;; *) echo "PRECISION: float64 or float32, not $precision" >&2; exit 2 ;; esac
case "$format" in
    omni) fmt_params="" ;;
    10x) fmt_params=", format: 10x" ;;
    h5ad) fmt_params=", format: h5ad, layout: sparse" ;;
    h5ad-dense) fmt_params=", format: h5ad, layout: dense" ;;
    *) echo "FORMAT: omni, 10x, h5ad or h5ad-dense, not $format" >&2; exit 2 ;;
esac

variant="$precision${fmt_params:+_$format}"
if [[ "$variant" == float64 ]]; then
    plan=benchmark-phase2.yaml; filters=filters/phase2
else
    plan="benchmark-phase2-$variant.yaml"; filters="filters/phase2-$variant"
    sed -e "s/dtype: float64/dtype: $precision/g" \
        -e "s/\(n_cells: [0-9]*, replicate: [0-9]*\)}/\1$fmt_params}/" benchmark-phase2.yaml > "$plan"
    [[ -z "$fmt_params" ]] || grep -q "replicate: [0-9]*$fmt_params}" "$plan" \
        || { echo "could not set the format on the input modules of $plan" >&2; exit 2; }
    pixi run python scripts/make_filters.py --plan "$plan" --out "$filters"
fi

tag="${variant}_$(bash scripts/hw_tag.sh)${REP:+_$REP}"
out="out-phase2_${tag}"
res="results/phase2_${tag}"
cores="${SLURM_CPUS_PER_TASK:-8}"
echo "plan $plan, filters $filters, output $out, results $res"

for s in ${SLICES:-pca knn cluster}; do
    pixi run ob run "$plan" --filter "$filters/slice-$s.yaml" --out-dir "$out" --cores "$cores" --continue-on-error
done
if [[ "${PIPELINES:-}" != none ]]; then
    PLAN="$plan" FILTERS="$filters" bash scripts/run_pipelines.sh "$out"
fi

# tables, then the report (phase2.py renders it at the end)
pixi run python analysis/phase2.py --from_out "$out" --output_dir "$res"
