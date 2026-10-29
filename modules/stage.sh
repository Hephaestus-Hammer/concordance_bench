#!/usr/bin/env bash
# ob entrypoint `stage`: run one script of a module, unchanged, under denet.
#
#   stage.sh --module <git url>@<40-char commit> --script <file.py> <the script's own arguments>
#
# --module and --script are this wrapper's own parameters and are not passed on; every
# other argument goes to the script exactly as ob would pass it if the plan referenced
# the module directly. The same approach as sc-brrr's brrr/prof.sh, one stage per job.
#
# 1. The module is checked out once per commit into $CONCORDANCE_MODULES (default
#    ~/.cache/concordance_bench/modules), under a lock, before monitoring starts: cloning
#    is not in the timings.
# 2. The script runs from that checkout (ob runs modules from their own directory) under
#      denet --json --quiet --gpu --write-env --out <output_dir>/denet.jsonl
#    --gpu: NVML sampling; without a usable GPU denet warns and carries on. --write-env:
#    host, NUMA and CPU-affinity record at the top of the trace. denet passes the exit code
#    through but swallows the script's output, so stdout and stderr go to
#    <output_dir>/module.log and are replayed into the job's log afterwards.
# 3. Without denet in the job's environment, the script runs unprofiled.
#
# A wrapper because ob 0.7.0 runs an entrypoint like "denet pca.py" as `python3 denet pca.py`.
set -euo pipefail

module="" script="" out="" args=()
while (($#)); do
  case $1 in
    --module) module=$2; shift 2 ;;
    --script) script=$2; shift 2 ;;
    --output_dir) out=$2; args+=("$1" "$2"); shift 2 ;;
    --output_dir=*) out=${1#--output_dir=}; args+=("$1"); shift ;;
    *) args+=("$1"); shift ;;
  esac
done
if [[ -z $module || -z $script || -z $out ]]; then
  echo "usage: stage.sh --module <git url>@<commit> --script <file.py> --output_dir <dir> [args...]" >&2
  exit 2
fi
url=${module%@*} sha=${module##*@}
if [[ $url == "$module" || ! $sha =~ ^[0-9a-f]{40}$ ]]; then
  echo "error: --module must be <git url>@<40-character commit>, got '$module'" >&2
  exit 2
fi

# 1. checkout, once per commit
cache=${CONCORDANCE_MODULES:-$HOME/.cache/concordance_bench/modules}
name=$(basename "${url%.git}")
dir=$cache/$name-$sha
mkdir -p "$cache"
(
  flock 9
  if [[ ! -d $dir ]]; then
    tmp=$(mktemp -d "$cache/.tmp-$name.XXXXXX")
    git -C "$tmp" init -q
    git -C "$tmp" fetch -q --depth 1 "$url" "$sha"
    git -C "$tmp" -c advice.detachedHead=false checkout -q FETCH_HEAD
    mv "$tmp" "$dir"
  fi
) 9>"$cache/.lock"
if [[ ! -f $dir/$script ]]; then
  echo "error: $script not found in $url@$sha" >&2
  exit 2
fi

# 2. run the script from its checkout, under denet if available. The script runs from
# another directory, so --output_dir is passed on as an absolute path (ob already passes
# absolute paths for the output directory and every input).
mkdir -p "$out"
abs=$(cd "$out" && pwd)
for i in "${!args[@]}"; do
  case ${args[$i]} in
    --output_dir) args[$((i + 1))]=$abs ;;
    --output_dir=*) args[$i]=--output_dir=$abs ;;
  esac
done
out=$abs
cd "$dir"
export PYTHONUNBUFFERED=1  # prints and tracebacks in order in module.log
if command -v denet >/dev/null; then
  rc=0
  denet --json --quiet --gpu --write-env --out "$out/denet.jsonl" \
    run bash -c 'exec python3 "$@" >"$0" 2>&1' "$out/module.log" "$script" ${args[@]+"${args[@]}"} || rc=$?
  cat "$out/module.log" >&2
  exit $rc
fi
# 3. no denet: unprofiled
exec python3 "$script" ${args[@]+"${args[@]}"}
