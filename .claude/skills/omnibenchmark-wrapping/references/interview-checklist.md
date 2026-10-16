# Questions to put to the module author before writing code

Ask these after reading the stage contract and finding the candidate upstream
function, and before writing the adapter. Put each as a concrete either/or with
your own recommendation attached — the author can then answer in one word. Open
questions ("how should this work?") waste the round-trip you are spending.

Ask only the ones the sources did not already answer. If the plan, a sibling
module or a validator settles a question, say so and move on:

> The validator already requires ≥10 columns and a first column named `PC1`, so
> I'll match that and not ask about output naming.

## A. The method

1. **Which function is the method?**
   "`irlba::irlba` directly, or `BiocSingular::runPCA(BSPARAM = IrlbaParam())`?
   They differ in centering and in what they return. I'd take the direct call —
   fewer layers between the plan and the algorithm."

2. **Which upstream defaults are we accepting?**
   "The tool defaults to `center = TRUE, scale = FALSE`. The sibling arms center
   and do not scale, so I'll keep both defaults and not expose them. Agree?"

3. **Is there more than one arm's worth of behaviour in one function?**
   "`RcppML::svd` takes `method` ∈ {lanczos, krylov, irlba, randomized,
   deflation}. One module with `--solver` as a swept parameter, or separate
   modules? I'd do one module — same reader, same writer, same environment."

## B. Parameters vs fixed defaults

This is the question that most often gets baked in wrong.

4. **Which arguments become plan `parameters`?**
   "I have `n_components`, `random_seed`, `solver`, `n_threads`. My proposal:
   `n_components` and `random_seed` are parameters (they are already swept on the
   sibling arms), `solver` is a parameter, and `n_threads` comes from the stage's
   `resources.cores` via `OMP_NUM_THREADS` rather than from the plan. Change any?"

5. **Should any parameter be required rather than defaulted?**
   The `omni-scrna` house rule is that every contract flag is required, so a run
   is reproducible from its invocation line alone, with no hidden defaults. The
   `scvi` and `rapids-singlecell` modules mark their method parameters
   `required=True` for the same reason. Confirm the author wants that, because
   it makes the plan more verbose.

6. **Is a parameter inert for some settings?**
   "`--random_seed` does nothing for the deterministic solver. Log it anyway, or
   reject the combination?" The `rapids-singlecell` module keeps a `SEEDED` set
   and records per run which solvers actually consumed the seed, so a seed sweep
   that produced identical replicates is visible in the log rather than inferred.

## C. Inputs

7. **How does the input file map to the tool's object?**
   "The stage input is a TENx-layout HDF5, genes × cells, CSC. The tool wants
   cells × genes. Transpose and materialise as a sparse matrix, or read via a
   delayed/out-of-core path? I'd materialise — the sibling arms do, and matching
   the read path is what makes the timings comparable."

8. **Does the tool need a different *kind* of input than the stage delivers?**
   "scVI needs raw counts; this stage's only input is the normalized, selected
   matrix. Options: (a) pair this module with a counts-passthrough normalisation
   arm and guard on integrality, (b) propose a new stage. I'd do (a) now and
   note (b) in the README." Never silently accept the wrong input.

9. **Are identifiers required to survive?**
   "The output TSVs are keyed by cell id and gene id. If the input matrix has no
   dimnames, should the module fail or fall back to positional indices?" The
   `rcppml` module's reader chooses failure: a nameless matrix would silently
   emit a table with the id column dropped.

## D. Outputs

10. **What exactly goes in each declared output?**
    "The stage declares `embedding_tsv` and `loadings_tsv`. For this tool I'd
    write scores (cells × k, first column `PC1`) and the gene rotation
    (genes × k). Ids in the first column, not as row names — matching the
    sibling arms. Confirm?"

11. **What if the tool has no natural value for a declared output?**
    "scVI's decoder is nonlinear, so there are no gene loadings. Write the
    correct shape filled with `NaN` and document it, so a consumer that needs
    loadings fails on the numbers instead of using zeros. Or should this stage
    not declare loadings at all?"

12. **Column naming for factors that are not principal components.**
    "NMF factors / latent dimensions are not PCs, but every downstream stage and
    validator in this benchmark reads `PC1..PCk`. Keep the `PC*` names with a
    comment, or introduce a second convention?" The exemplars keep `PC*`.

## E. Degenerate and edge cases

13. **Fewer cells or genes than requested components** — fail, or clamp `k` and
    log the clamp?
14. **All-zero rows/columns, or a constant gene** — does the upstream handle it,
    or does it return `NaN` silently?
15. **Hardware the run may not have** (a GPU arm on a CPU box) — fail, or fall
    back? The `rcppml` module refuses `--backend gpu` without a visible device
    rather than accepting the upstream's warn-and-fall-back, because "a CPU run
    recorded as a GPU arm is worse than a failed job."
16. **Non-determinism** — is the tool reproducible given the seed, and on how
    many threads? If thread count changes the numbers, that belongs in the
    README and probably in the plan's `resources`. To test it and assign a
    tier, use the `omnibenchmark-reproducibility` skill.

## F. Scope of this increment

17. **Which single entrypoint are we landing first?**
    "The tool covers PCA, kNN and clustering. I'll do PCA end to end — adapter,
    `check`, one real run, PR — and open an issue for the other two. Agree?"
18. **Which invariants should the module assert?**
    "I plan three: output file non-empty; row count equals input cell count;
    column count equals `--n_components`. Anything else you would not trust a
    reviewer to catch by eye?"

## Recording the answers

Put the answers in the module's `README.md` as a short "Design decisions"
section, and the ones that constrain the code as one-line comments next to the
code they constrain. The exemplar modules do this heavily — `rcppml/pca.R`
explains in four comment lines why there is no transpose and how `u`/`v` swap
roles relative to the cells-as-rows modules. Six months later that comment is
the only record of the conversation.
