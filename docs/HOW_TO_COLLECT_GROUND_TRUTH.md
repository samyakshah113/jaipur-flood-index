# How to collect ground truth

**This is the most valuable part of the project and nobody else will do it for you.**

Anyone can download elevation data and produce a coloured map. What separates this from
a school poster is being able to answer: *how do you know it is right?*

The answer is a list of places in Jaipur that really waterlogged, and a list that really
did not, collected by you, with sources. Forty good observations will do more for this
project than another thousand lines of code.

---

## The file you are building

`data/waterlogging_observations.csv`

| column | what goes in it |
|---|---|
| `name` | What to call the place — "Sindhi Camp bus stand underpass" |
| `lat`, `lon` | Coordinates. Right-click the spot in Google Maps and click the numbers to copy them |
| `flooded` | `1` if it waterlogged, `0` if it stayed passable |
| `source` | Where you learned this — a news URL, "photographed 2025-07-19", "shopkeeper at the corner" |
| `date` | When, if you know it |
| `depth_cm` | Optional. Roughly how deep — ankle ≈ 15, knee ≈ 45, waist ≈ 90 |
| `notes` | Anything else. "Water stood for 3 days", "drain visibly blocked" |

---

## The mistake that ruins most student validation

**You need places that did NOT flood.**

If you only record flooding, a model that declares the entire city high-risk scores
perfectly. Negative examples are what make the test mean anything.

They are harder to collect because nobody photographs a road that is fine. Three ways
to find them:

1. **Look in the background of flood photos.** A picture of a submerged intersection
   often shows a perfectly dry road behind it. Both are observations.
2. **Streets nobody complained about.** During a storm that generated dozens of
   complaints, the roads absent from that list are informative.
3. **Walk a route during or just after heavy rain.** Record every junction — wet and
   dry. This is the highest-quality data in the whole project because you controlled
   the collection.

Aim for **at least 20 flooded and 20 dry.** Below that, the confidence interval on your
AUC will be so wide that the number tells you almost nothing — and `validate.py` will
warn you about exactly this.

---

## Where to look

**Local news archives.** *Dainik Bhaskar*, *Rajasthan Patrika*, *Times of India Jaipur*,
*Dainik Navajyoti*. Search in Hindi as well as English — the Hindi coverage of local
waterlogging is far more detailed. Useful search terms:

- जयपुर जलभराव
- जयपुर बारिश सड़क पानी
- Jaipur waterlogging *(plus a specific colony name)*

**Target the big storms specifically.** Run `fetch_rainfall.py` first — it prints the
ten wettest days on record for Jaipur. Search the news for those exact dates. That is
far more efficient than searching generally, and it means your observations are tied to
a known rainfall event rather than a vague "it floods sometimes".

**Social media.** X and Instagram around those dates, geotagged. People post videos of
flooded streets with the location in the caption. Cross-check anything you find.

**Your own eyes.** You live there. This is the strongest data you will get, and it is
the honest core of the "personal connection" that this project is actually about —
not a paragraph written to sound good on an application.

**Ask.** Autorickshaw drivers know exactly which underpasses become impassable, because
their income depends on it. Shopkeepers know which streets flood because they have to
move stock. A afternoon of asking is a genuine primary-source survey.

---

## Rules for keeping it honest

**Record the source for every single point.** An observation without a source is an
assertion. This column is what makes the file evidence.

**Do not adjust an observation because the model disagrees with it.** This is the
cardinal sin. If your model says a place is low risk and it demonstrably floods, that is
a finding about your model, and it is more interesting than agreement would have been.
Investigate why: is the cell too coarse? Is there drainage OSM does not know about? Is
a canal embankment blocking flow in a way the terrain data cannot see?

**Collect before you look at the map.** If you build the observation list after studying
the model output, you will unconsciously pick points that agree with it. Collect first,
score second. This is the same reason clinical trials are pre-registered.

**Note when you are unsure.** A `notes` entry saying "reported in one tweet, could not
confirm" is more useful than quiet false confidence.

---

## What good looks like

A finished file with 45 rows, of which 24 are flooded and 21 dry, drawn from three named
storms, with sources spanning local news, your own photographs, and a handful of
conversations — and an AUC of 0.73 with a confidence interval of 0.61 to 0.84.

That is a real result. It is modest, it is defensible, and you can explain every number
in it. It is worth incomparably more than an unvalidated map that claims 95% accuracy.
