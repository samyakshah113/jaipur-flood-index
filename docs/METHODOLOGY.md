# Methodology

Every modelling decision in this project, with the reasoning and the objection.

---

## 1. Why an index and not a machine-learning classifier

The obvious framing — "train a model to predict flooding" — requires labelled data:
thousands of locations with a known flooded / not-flooded outcome. That data does not
exist publicly for Jaipur. Building a supervised model without it means either inventing
labels or quietly training on something that is not what you claim.

So the primary model is a **weighted multi-criteria index**, which is the standard
approach in flood-vulnerability literature when labels are scarce. It encodes known
hydrology rather than learning from examples.

A supervised layer is available as an *extension* once enough ground-truth observations
exist (see `notebooks/` section 9). At that point the honest comparison is: does a model
trained on 40 real points beat the physics-based index? Often it does not, and that is a
result worth reporting.

## 2. Hazard: why these five variables

| Variable | Why it belongs |
|---|---|
| Topographic Wetness Index | Combines "how much water arrives" with "how slowly it leaves" in one number. The single best terrain predictor of surface saturation (Beven & Kirkby, 1979). |
| Depression depth | How deep a closed hollow the cell sits in. Water entering has no gravity-driven exit. |
| Flow accumulation | Upstream contributing area. Distinguishes a cell that catches its own rain from one collecting runoff from half a square kilometre. |
| Distance to drainage | Proximity to a mapped channel is the main engineered escape route. |
| Slope (inverted) | Flat ground sheds water slowly. Low slope, high risk. |

**The obvious objection:** TWI is *computed from* slope and flow accumulation, so the
three are correlated and the hazard score double-counts. This is true. It is a genuine
weakness of additive indices. The mitigation is the sensitivity analysis in §5 — if the
conclusion survives large changes in weighting, the double-counting is not driving the
answer. A cleaner alternative would be principal component analysis to decorrelate the
inputs first; that is a legitimate next step for this project.

## 3. Sensitivity: the part to be most careful about

The research question concerns low-income neighbourhoods. Ward-level income data for
Jaipur is not publicly available at 300 m resolution, so the model uses proxies:

- **Unpaved road share** — a proxy for municipal infrastructure investment
- **Settlement density** — very high building density with small footprints is
  characteristic of informal settlement
- **Absence of mapped drainage** — a proxy for un-serviced areas

**These are proxies and they can be wrong about real neighbourhoods.** A newly developed
area may have unpaved roads and no deprivation. A dense historic bazaar in the walled
city is dense without being poor. Any output touching this component should be described
as *"areas with infrastructure characteristics associated with disadvantage"*, never as
*"poor areas"*. The distinction matters because getting it wrong misdirects resources
away from people who need them.

**Better data, if you can get it:** Census 2011 ward-level tables give household amenity
access (drainage connection, water source, roof material) at a usable resolution. That
would replace the proxies with measurements. It requires manual extraction from the
Census tables and matching to ward boundaries — genuinely worthwhile as a v2.

## 4. Why percentile normalisation

Min-max scaling, `(x - min) / (max - min)`, is the intuitive choice and it fails here.

Flow accumulation is extremely right-skewed: cells on a main drainage line can score
thousands of times the median. Min-max would map the entire city into the bottom few
percent of the scale, and the map would show one bright line against a uniform
background — technically correct, practically useless.

Percentile rank asks "what fraction of cells score lower?", which preserves
discrimination across the whole distribution.

**The cost, stated plainly:** rank discards magnitude. The index can say a cell is worse
than 90% of Jaipur; it can never say a cell is in absolute danger. This is a
prioritisation tool, not a hazard assessment.

## 5. Sensitivity analysis: the weights problem

The weights (hazard 0.50, exposure 0.25, sensitivity 0.25) are a judgement call. A fair
critic points out that different weights give a different map.

Rather than defend the choice, the project tests it. The index is recomputed 200 times
with each weight randomly perturbed by up to ±50% and renormalised. Two outputs:

- **`rank_stability`** — the fraction of trials in which the cell landed in the worst
  10%. Cells at ~1.0 are high risk under essentially any defensible weighting.
- **`rank_volatility`** — the spread of the cell's rank across trials.

Only cells with high stability are reported as priority sites. Everything else is
labelled as weight-dependent.

## 6. Validation

`AUC` is the reported metric. Given a randomly chosen flooded location and a randomly
chosen dry one, AUC is the probability the index scored the flooded one higher.

Chosen over accuracy because accuracy depends on an arbitrary threshold and is inflated
by class imbalance. For a ranking tool, AUC is the correct measure.

Reported alongside:
- **Bootstrap 95% confidence interval** — with a small sample the point estimate alone
  overstates precision
- **Baseline comparison** — the AUC of the full index against single variables. If
  "relative elevation" alone matches the composite, the composite is not earning its
  complexity, and that must be reported rather than buried.

## 7. Known limitations

1. **Resolution.** 300 m cells cannot represent a blocked inlet or a kerb.
2. **Elevation vintage.** SRTM-derived data is from 2000. Jaipur has been extensively
   regraded since; new construction and road-raising are invisible.
3. **No hydraulic model.** Real flood modelling solves shallow-water equations over time.
   This is a static index. It says where water tends to collect, not how deep or how long.
4. **No drainage capacity.** A drain's presence is used; its diameter, condition and
   whether it is blocked are unknown and matter enormously.
5. **OSM completeness bias.** Better-mapped areas appear to have more infrastructure.
   Since mapping effort correlates with affluence, this may bias the sensitivity
   component in a direction that *understates* risk in poorly-mapped areas — the
   opposite of what you want.
6. **Rainfall is spatially uniform.** ERA5 is a ~25 km grid; the whole city gets the same
   rainfall in this model. Real flash flooding often comes from a localised cloudburst.

Limitation 5 is the one to think hardest about, because it cuts against the project's
own stated purpose.

## 8. What a v2 should do

- Census 2011 ward amenity data in place of infrastructure proxies
- Sentinel-1 SAR imagery from immediately after a major storm — radar sees through cloud,
  and standing water is a strong dark signal. This would give real observed flood extent
  and turn the project into genuine supervised learning
- Principal component analysis to handle the correlated hazard variables
- A simple hydraulic routing model over the DEM rather than a static index

## References

- Beven, K. & Kirkby, M. (1979). A physically based, variable contributing area model of
  basin hydrology. *Hydrological Sciences Bulletin*, 24(1), 43–69.
- Barnes, R., Lehman, C. & Mulla, D. (2014). Priority-flood: An optimal depression-filling
  and watershed-labeling algorithm for digital elevation models. *Computers & Geosciences*, 62, 117–127.
- O'Callaghan, J. & Mark, D. (1984). The extraction of drainage networks from digital
  elevation data. *Computer Vision, Graphics and Image Processing*, 28(3), 323–344.
