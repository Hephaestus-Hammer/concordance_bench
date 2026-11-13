#!/bin/bash
# Print a short hardware tag for output folder names: <GPU model>_<N>core, or cpu_<N>core
# without a GPU. Cores: the Slurm allocation if there is one, else every core on the host.
#   scripts/hw_tag.sh            ->  A100-80GB_8core
set -euo pipefail
cores="${SLURM_CPUS_PER_TASK:-$(nproc)}"
gpu=""
if command -v nvidia-smi >/dev/null 2>&1; then
    gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || true)
fi
if [[ -z "$gpu" ]]; then
    echo "cpu_${cores}core"
    exit 0
fi
# "NVIDIA A100-SXM4-80GB" -> "A100-SXM4-80GB"; anything but letters, digits, '-' becomes '-'
gpu=$(echo "$gpu" | sed -E 's/^(NVIDIA|Tesla) +//; s/[^A-Za-z0-9-]+/-/g; s/-+/-/g; s/^-|-$//g')
echo "${gpu}_${cores}core"
