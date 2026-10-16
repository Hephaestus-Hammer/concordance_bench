<!-- ob-version: OmniBenchmark CLI, version 0.7.0 -->

# `ob` command reference

Generated from the installed binary (`ob --version` → `OmniBenchmark CLI, version 0.7.0`) by
`scripts/refresh_cli_reference.py`. Do not edit by hand.

## Commands

- [`ob`](#ob)
- [`ob cite`](#ob-cite)
- [`ob collect`](#ob-collect)
- [`ob collect performance`](#ob-collect-performance)
- [`ob create`](#ob-create)
- [`ob create benchmark`](#ob-create-benchmark)
- [`ob create module`](#ob-create-module)
- [`ob describe`](#ob-describe)
- [`ob describe snakemake`](#ob-describe-snakemake)
- [`ob describe status`](#ob-describe-status)
- [`ob describe topology`](#ob-describe-topology)
- [`ob remote`](#ob-remote)
- [`ob remote files`](#ob-remote-files)
- [`ob remote files checksum`](#ob-remote-files-checksum)
- [`ob remote files download`](#ob-remote-files-download)
- [`ob remote files list`](#ob-remote-files-list)
- [`ob remote policy`](#ob-remote-policy)
- [`ob remote policy create`](#ob-remote-policy-create)
- [`ob remote version`](#ob-remote-version)
- [`ob remote version create`](#ob-remote-version-create)
- [`ob remote version diff`](#ob-remote-version-diff)
- [`ob remote version list`](#ob-remote-version-list)
- [`ob run`](#ob-run)
- [`ob validate`](#ob-validate)
- [`ob validate module`](#ob-validate-module)
- [`ob validate plan`](#ob-validate-plan)
- [`ob archive`](#ob-archive)
- [`ob dashboard`](#ob-dashboard)

## `ob`

```text
Usage: ob [OPTIONS] COMMAND [ARGS]...

  OmniBenchmark Command Line Interface (CLI).

Options:
  --debug / --no-debug  Enable debug mode
  --version             Show the version and exit.
  --help                Show this message and exit.

Commands:
  cite         Extract citation metadata from CITATION.cff...
  collect      Gather scattered benchmark artefacts into...
    collect performance Gather all performance.txt files into a...
  create       Create new benchmarks or modules from templates.
    create benchmark  Create a new benchmark from a template.
    create module     Create a new module from a template.
  describe     Describe benchmarks and/or information about them.
    describe snakemake  Export a snakemake computational graph to...
    describe topology   Export benchmark topology to MERMAID...
    describe status     Show the status of a benchmark.
  remote       Manage remote storage.
    remote files      Manage files in remote storage.
    remote version    Manage benchmark versions.
    remote policy     Manage storage policies. (DEPRECATED)
  run          Run a benchmark.
  validate     Validate benchmarks and modules.
    validate plan       Validate benchmark YAML plan structure.
    validate module     Validate module (metadata, try to run).
  archive      Archive a benchmark and its artifacts.
  dashboard    Generate a dashboard from benchmark results.
```

## `ob cite`

```text
Usage: ob cite [OPTIONS]

  Extract citation metadata from CITATION.cff files in benchmark modules.

  Automatically clones repositories to temporary directories if not found
  locally. By default, runs in warn mode and converts errors to warnings. Use
  --strict to fail on errors instead.

Options:
  --debug / --no-debug            Enable debug mode
  -b, --benchmark PATH            Path to benchmark yaml file or benchmark id.
                                  [required]
  -f, --format [json|yaml|bibtex]
                                  Output format for citation information.
  --strict                        Fail on errors instead of converting them to
                                  warnings (default: warn mode).
  --out PATH                      Output file to write results to.
  --help                          Show this message and exit.
```

## `ob collect`

```text
Usage: ob collect [OPTIONS] COMMAND [ARGS]...

  Gather scattered benchmark artefacts into combined tables.

Options:
  --help  Show this message and exit.

Commands:
  performance  Gather all performance.txt files into a combined...
```

## `ob collect performance`

```text
Usage: ob collect performance [OPTIONS]

  Gather all performance.txt files into a combined performances.tsv.

  Walks the output directory, parses every Snakemake benchmark file, and
  enriches each row with its stage, module, parameters and lineage. The
  resulting out/performances.tsv is consumed by `ob dashboard`.

Options:
  --debug / --no-debug  Enable debug mode
  -o, --out-dir PATH    Output directory containing benchmark results
                        (default: out).
  --help                Show this message and exit.
```

## `ob create`

```text
Usage: ob create [OPTIONS] COMMAND [ARGS]...

  Create new benchmarks or modules from templates.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.

Commands:
  benchmark  Create a new benchmark from a template.
  module     Create a new module from a template.
```

## `ob create benchmark`

```text
Usage: ob create benchmark [OPTIONS] [PATH]

  Create a new benchmark from a template.

  This command scaffolds a new benchmark project structure using copier
  templates. It creates all necessary configuration files, directory
  structure, and example modules to get you started with your benchmark.

Options:
  --debug / --no-debug            Enable debug mode
  --no-input                      Do not prompt for parameters and only use
                                  defaults
  --non-interactive               Non-interactive mode (requires all mandatory
                                  parameters as flags)
  --name TEXT                     Name of the benchmark
  --author-name TEXT              Author name
  --author-email TEXT             Author email
  --license [MIT|Apache-2.0|GPL-3.0|BSD-3-Clause|CC0-1.0]
                                  License for the benchmark
  --description TEXT              Description of the benchmark
  --help                          Show this message and exit.
```

## `ob create module`

```text
Usage: ob create module [OPTIONS] PATH

  Create a new module from a template.

  This command scaffolds a new OmniBenchmark module project structure using
  copier templates. It creates the necessary configuration files
  (CITATION.cff, omnibenchmark.yaml), a sample entrypoint script, and
  documentation to get you started with your module development.

  When using --benchmark and --for-stage, the generated entrypoint will
  include CLI argument parsing for the specific inputs required by that stage.

Options:
  --debug / --no-debug            Enable debug mode
  -b, --benchmark TEXT            Path or URL to benchmark YAML file (for
                                  stage-specific input parsing)
  --for-stage TEXT                Stage ID to generate module for (requires
                                  --benchmark)
  --no-input                      Do not prompt for parameters and only use
                                  defaults
  --non-interactive               Non-interactive mode (requires all mandatory
                                  parameters as flags)
  --name TEXT                     Name of the module
  --author-name TEXT              Author name
  --author-email TEXT             Author email
  --license [MIT|Apache-2.0|GPL-3.0-or-later|BSD-3-Clause|CC0-1.0]
                                  License for the module
  --description TEXT              Description of the module
  --entrypoint [run.R|run.py|run.sh]
                                  Main entrypoint script for the module
  --help                          Show this message and exit.
```

## `ob describe`

```text
Usage: ob describe [OPTIONS] COMMAND [ARGS]...

  Describe benchmarks and/or information about them.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.

Commands:
  snakemake  Export a snakemake computational graph to dot format.
  status     Show the status of a benchmark.
  topology   Export benchmark topology to MERMAID diagram format.
```

## `ob describe snakemake`

```text
Usage: ob describe snakemake [OPTIONS] BENCHMARK

  Export a snakemake computational graph to dot format.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.
```

## `ob describe status`

```text
Usage: ob describe status [OPTIONS] BENCHMARK

  Show the status of a benchmark.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  --out-dir TEXT        Output folder name (local only).
  --missing_files       Show missing files in the status report.
  --reason              Show reason for missing files in the status report.
  --logs                Show logs for missing files in the status report.
  --json                Return the status report as JSON.
  --html                Return the status report as HTML.
  --html-file TEXT      Output HTML file name.
  --force               If HTML file exists, overwrite it.
  --help                Show this message and exit.
```

## `ob describe topology`

```text
Usage: ob describe topology [OPTIONS] BENCHMARK

  Export benchmark topology to MERMAID diagram format.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug            Enable debug mode
  --show-params / --no-show-params
                                  Whether to write parameters to the mermaid
                                  output.
  --compact-params / --no-compact-params
                                  Whether to write parameters compactly (only
                                  used if --show-params).
  --help                          Show this message and exit.
```

## `ob remote`

```text
Usage: ob remote [OPTIONS] COMMAND [ARGS]...

  Manage remote storage.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.

Commands:
  files    Manage files in remote storage.
  policy   Manage storage policies. (DEPRECATED)
  version  Manage benchmark versions.
```

## `ob remote files`

```text
Usage: ob remote files [OPTIONS] COMMAND [ARGS]...

  Manage files in remote storage.

Options:
  --help  Show this message and exit.

Commands:
  checksum  Generate md5sums of all benchmark outputs.
  download  Download all or specific files for a benchmark.
  list      List all or specific files for a benchmark.
```

## `ob remote files checksum`

```text
Usage: ob remote files checksum [OPTIONS] BENCHMARK

  Generate md5sums of all benchmark outputs.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.
```

## `ob remote files download`

```text
Usage: ob remote files download [OPTIONS] BENCHMARK

  Download all or specific files for a benchmark.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  -t, --type TEXT       File types. Options: all, code, inputs, outputs, logs,
                        performance.
  -s, --stage TEXT      Stage to download files from.
  -m, --module TEXT     Module to download files from.
  -i, --id TEXT         File id to download.
  -o, --overwrite       Overwrite existing files.
  --help                Show this message and exit.
```

## `ob remote files list`

```text
Usage: ob remote files list [OPTIONS] BENCHMARK

  List all or specific files for a benchmark.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  -t, --type TEXT       File types. Options: all, code, inputs, outputs, logs,
                        performance.
  -s, --stage TEXT      Stage to list files for.
  -m, --module TEXT     Module to list files for.
  -i, --id TEXT         File id/type to list.
  --help                Show this message and exit.
```

## `ob remote policy`

```text
Usage: ob remote policy [OPTIONS] COMMAND [ARGS]...

  Manage storage policies. DEPRECATED: use your cloud provider's IAM tooling
  directly. (DEPRECATED)

Options:
  --help  Show this message and exit.

Commands:
  create  Generate an S3/MinIO IAM policy for a benchmark bucket.
```

## `ob remote policy create`

```text
Usage: ob remote policy create [OPTIONS]

  Generate an S3/MinIO IAM policy for a benchmark bucket.

  This command generates a least-privilege AWS IAM policy JSON that can be
  used to create access keys in MinIO or AWS. The policy allows full S3
  operations on the bucket but denies deletion and governance bypass.

  You can either: - Provide a benchmark YAML file (-b/--benchmark) to read the
  bucket name from storage.bucket_name - Provide the bucket name directly
  (--bucket)

Options:
  --debug / --no-debug  Enable debug mode
  -b, --benchmark PATH  Path to benchmark YAML file.
  --bucket TEXT         S3 bucket name. If not provided, reads from benchmark
                        YAML.
  --help                Show this message and exit.
```

## `ob remote version`

```text
Usage: ob remote version [OPTIONS] COMMAND [ARGS]...

  Manage benchmark versions.

Options:
  --help  Show this message and exit.

Commands:
  create  Create a new benchmark version.
  diff    Show differences between 2 benchmark versions.
  list    List all available benchmark versions.
```

## `ob remote version create`

```text
Usage: ob remote version create [OPTIONS] BENCHMARK

  Create a new benchmark version.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.
```

## `ob remote version diff`

```text
Usage: ob remote version diff [OPTIONS] BENCHMARK

  Show differences between 2 benchmark versions.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  -v1, --version1 TEXT  Reference version.  [required]
  -v2, --version2 TEXT  Version to compare with.  [required]
  --help                Show this message and exit.
```

## `ob remote version list`

```text
Usage: ob remote version list [OPTIONS] BENCHMARK

  List all available benchmark versions.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.
```

## `ob run`

```text
Usage: ob run [OPTIONS] BENCHMARK [SNAKEMAKE_ARGS]...

  Run a benchmark.

  BENCHMARK: Path to benchmark YAML file.

  This command: 1. Fetches and caches all module repositories 2. Resolves
  modules and generates an explicit Snakefile 3. Runs snakemake on the
  generated Snakefile

  Any arguments after -- are passed directly to snakemake.

  Examples:

    ob run benchmark.yaml                    # Run full benchmark   ob run
    benchmark.yaml --cores 8          # Run with 8 cores   ob run
    benchmark.yaml --dry              # Generate Snakefile only   ob run
    benchmark.yaml --dirty            # Allow local paths with uncommitted
    changes   ob run benchmark.yaml --unpinned         # Allow branch refs on
    remote repos   ob run benchmark.yaml -m M1              # Dev mode: run
    only module M1   ob run benchmark.yaml --telemetry         # Emit
    OTLP/JSONL telemetry to stdout   ob run benchmark.yaml -- --rerun-triggers
    mtime  # Pass flags to snakemake   ob run benchmark.yaml -- --forceall
    # Force re-run all rules

Options:
  --debug / --no-debug     Enable debug mode
  -c, --cores INTEGER      Use at most N CPU cores in parallel. Default is 1.
  -d, --dry                Dry run (only generate Snakefile, don't execute).
  -k, --continue-on-error  Go on with independent jobs if a job fails (--keep-
                           going in snakemake).
  --out-dir TEXT           Output folder name. Default: `out`
  --dirty                  Allow local path module references with uncommitted
                           changes. Use for development only.
  --unpinned               Allow unpinned branch references on remote repos
                           (resolved to HEAD at run time). Use for development
                           only.
  --use-remote-storage     Execute and store results remotely using S3 storage
                           configured in the benchmark YAML.
  -m, --module TEXT        Run only the sub-graph needed for a single module
                           (development mode). Prunes all stages after the
                           target module's stage and keeps only the first
                           upstream input × parameter expansion for each
                           module.
  --telemetry              Emit OTLP telemetry as JSON Lines to stdout
                           (disables Rich progress).
  --telemetry-output PATH  Write telemetry to file instead of stdout. Allows
                           Rich progress to remain active. Implies
                           --telemetry.
  --with-capability NAME   Declare a host capability available on this machine
                           (repeatable). Modules whose requires_capabilities
                           are not all provided are pruned. Example: --with-
                           capability gpu --with-capability large_mem
  --until TEXT             Stop the pipeline at and including the named stage.
                           Only the named stage and its transitive ancestors
                           are kept in the resolved DAG, and metric collectors
                           whose inputs reference pruned stages are skipped.
  --filter FILE|BLOB       Run a slice of the benchmark defined by an obfilter
                           selection: a path to a YAML/JSON file of picks, a
                           file containing a packed blob, or an inline packed
                           blob. Prunes the DAG to the picked
                           stages/modules/param-combos. Incompatible with
                           -m/--module.
  --allow-drift            With --filter: if the benchmark has changed since
                           the filter was made and some selected
                           stages/modules/parameters no longer exist, run the
                           part that still matches instead of erroring.
                           Skipped selections are listed as warnings.
  --help                   Show this message and exit.
```

## `ob validate`

```text
Usage: ob validate [OPTIONS] COMMAND [ARGS]...

  Validate benchmarks and modules.

Options:
  --debug / --no-debug  Enable debug mode
  --help                Show this message and exit.

Commands:
  module  Validate module (metadata, try to run).
  plan    Validate benchmark YAML plan structure.
```

## `ob validate module`

```text
Usage: ob validate module [OPTIONS] [PATH]

  Validate module (metadata, try to run).

  Validates a module repository at PATH. Defaults to current directory if not
  specified.

  Checks: - Required files exist (CITATION.cff, LICENSE, omnibenchmark.yaml) -
  CITATION.cff is valid and has required fields - License consistency between
  CITATION.cff and LICENSE file

  By default, shows warnings but doesn't fail. Use --strict to fail on
  warnings.

Options:
  --strict  Treat warnings as errors and fail on any validation issue.
  --help    Show this message and exit.
```

## `ob validate plan`

```text
Usage: ob validate plan [OPTIONS] BENCHMARK

  Validate benchmark YAML plan structure.

  Checks: - YAML syntax is valid - Required fields are present - Data types
  are correct - References between stages/modules are valid - Software
  environment backends are properly configured

Options:
  --help  Show this message and exit.
```

## `ob archive`

```text
Usage: ob archive [OPTIONS] BENCHMARK

  Archive a benchmark and its artifacts.

  BENCHMARK: Path to benchmark YAML file.

Options:
  --debug / --no-debug            Enable debug mode
  -c, --code                      Archive benchmarking code (repos).
  -s, --software                  Archive software environments.
  -r, --results                   Archive results files.
  --compression [none|deflated|bzip2|lzma|gzip]
                                  Compression method. 'gzip' creates a tar.gz
                                  archive, others create ZIP archives.
                                  [default: gzip]
  --compresslevel INTEGER         Compression level (1-9, higher is better
                                  compression).  [default: 9]
  -n, --dry-run                   Do not create the archive, just show what
                                  would be done.
  --use-remote-storage            Download results from remote storage for
                                  archiving. Default False.
  --out-dir TEXT                  Local directory name to archive from (local-
                                  only mode). Default: `out`
  -o, --output-file PATH          Custom output file path for the archive.
                                  Extension must match compression type:
                                  none/deflated (.zip), bzip2 (.bz2), lzma
                                  (.xz), gzip (.tar.gz).
  --help                          Show this message and exit.
```

## `ob dashboard`

```text
Usage: ob dashboard [OPTIONS] BENCHMARK

  Generate a dashboard from benchmark results.

  This command generates a dashboard from the performance data collected
  during benchmark execution.

Options:
  --debug / --no-debug  Enable debug mode
  -f, --format [bettr]  Dashboard format to generate (default: bettr).
  -o, --out-dir PATH    Output directory containing benchmark results
                        (default: out).
  --help                Show this message and exit.
```

