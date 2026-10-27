# Metrics

Definition of every metric in `analysis/concordance.py`, and what "agreement"
means for each. All metrics compare two runs on the same cells, aligned by cell
id.

## Pair categories

Every pair of runs is labelled by what differs between their lineages
(`analysis/load.py`, `pair_category`):

- the stages whose module or settings differ, joined by `+` (`pca`, `knn`,
  `pca+knn`, `cluster`, …);
- `seed` if only random seeds differ;
- `replicate` if only the input replicate differs.

`seed` and `replicate` pairs are the noise floor. A stage difference is only
interesting if its pairs fall outside that spread.

## PCA |cos|

Per component *i*: 1 − |cos(a<sub>i</sub>, b<sub>i</sub>)|, where a<sub>i</sub> and
b<sub>i</sub> are the cell scores of component *i* in the two runs. The absolute
value makes it sign-invariant (component signs are arbitrary). 0 = same
direction; 1 = orthogonal. Plotted on a log scale with 0 drawn at 10<sup>−16</sup>.

Components with nearly equal variance can swap or rotate into each other without
any change to the subspace, so a large value in a late component is not by
itself a disagreement; see the subspace angle.

## PCA subspace

The largest principal angle (degrees) between the spans of the first *k*
components of the two runs (`scipy.linalg.subspace_angles` on the score
matrices), for *k* = 10, 20, 50. 0° = the same subspace. Insensitive to sign,
order and rotation within the span.

## kNN overlap

Per cell: the number of neighbours found in both graphs divided by the size of
the larger of the two neighbour sets. The cell itself is never counted, whether
or not a module stores it, so with `n_neighbors = 15` each set has 14 cells.
Neighbours at distance 0 (duplicate cells) are counted. Reported as the mean
over cells and as the share of cells whose neighbour sets are identical.

## ARI

Adjusted Rand index between two partitions of the same cells
(`sklearn.metrics.adjusted_rand_score`). 1 = identical partitions up to
renaming of the clusters; about 0 = no more agreement than chance. Used between
pipelines and against the annotation (`truths`, `truths_cl` in the truth file).
Against the annotation, a different number of clusters from annotated types
keeps the ARI below 1 for every pipeline, so pipelines are compared with each
other, not with 1. NMI (`normalized_mutual_info_score`) is reported alongside in
the TSV.
