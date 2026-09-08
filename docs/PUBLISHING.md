# Publishing this and putting it on applications

Two separate jobs: get the work online where anyone can check it, and describe it
accurately in about 150 characters.

---

# Part 1 — GitHub

## Setting up (once)

1. Make a GitHub account at github.com. **Use a username you would put on a CV** —
   `samyakshah` beats `xX_coder_Xx`. You cannot change this easily later.
2. Create a new repository called `jaipur-flood-index`. Public. Do not tick "add a README"
   — you already have one.
3. Follow the "push an existing repository" commands GitHub shows you:

```bash
cd jaipur-flood-index
git init
git add .
git commit -m "Flood vulnerability index for Jaipur from open data"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/jaipur-flood-index.git
git push -u origin main
```

## Making the map viewable in a browser

A `.html` file sitting in a GitHub repo does not render — visitors get source code.
GitHub Pages fixes that and is free.

1. Create a folder called `docs/site/` and copy `outputs/jaipur_flood_risk_map.html`
   into it as `index.html`
2. Repository → **Settings** → **Pages**
3. Source: **Deploy from a branch**, branch `main`, folder `/docs`
4. Wait about a minute

Your map is now live at `https://YOUR-USERNAME.github.io/jaipur-flood-index/site/`

**Put that link at the top of your README.** A repo where someone can see the result in
one click gets looked at; one that requires cloning and installing does not.

## Things that make a repo look serious

Most of these are already done. Do not skip the last one.

- A README that opens with what the project does, not how to install it ✓
- Honest limitations stated prominently, not buried at the bottom ✓
- Tests that actually verify something ✓
- A licence ✓
- One command that runs everything ✓
- **Commit history that shows the work.** Do not upload everything in a single commit
  called "first commit". Commit as you go, with messages saying what changed and why.
  A history showing you found and fixed the exposure-filter bug is evidence of thinking.

## Do not fake it

No backdating commits, no inflating contributions, no listing yourself as author of code
you did not understand. Anyone who cares enough to check can check, and getting caught
costs more than the project is worth. If you used this code as a starting point, say so
in the README and describe what you changed and extended — that is a normal and
respectable thing to write.

---

# Part 2 — Common App

**Current limits (2026–27 cycle):** activity description **150 characters**, position
**50**, organisation name **100**. Ten activity slots, five honors at 100 characters each.
Essay 650 words, Additional Information 300 words.

## The activities entry

**Activity type:** Science/Math, or Computer/Technology

**Position/Leadership (50):**
```
Independent researcher and developer
```

**Organization (100):**
```
Self-directed project
```

**Description (150).** Pick based on what is actually true when you submit.

If you have collected ground truth and validated it:
```
Built open-data flood risk model for Jaipur: terrain hydrology + OSM data across 300m grid. Validated on 40 field observations, AUC 0.7x.
```
*(133 characters. Replace 0.7x with your real number.)*

If you have shared it with a municipal body:
```
Modelled monsoon flood risk across Jaipur from satellite terrain and open map data; validated against field observations; shared with JMC.
```
*(137 characters.)*

If it is built but not yet validated — be accurate, not aspirational:
```
Built and published open-source flood risk model mapping Jaipur's waterlogging-prone areas from terrain, drainage and settlement data.
```
*(132 characters.)*

**Rules for these 150 characters:**

- **Lead with the verb.** "Built", "modelled", "validated". Not "Was responsible for".
- **A number beats an adjective.** "40 field observations" says more than "extensive".
- **Never claim what you cannot show.** If you write "AUC 0.78", have the notebook that
  produces it. Interviews happen.
- **Do not write "using machine learning and AI"** unless you trained a model and can
  explain it. The composite index is not machine learning, and calling it that is the
  kind of thing that unravels in thirty seconds of questioning.

## Honors

Only if you actually win something. Do not invent categories.

```
Selected for [competition/conference] — Jaipur flood risk model
```

Real options worth entering, if the timing works: Regeneron ISEF (via an affiliated
Indian fair), NASA Space Apps Challenge, Google Science Fair-style contests, IEEE student
competitions, or a poster at a regional urban-planning or disaster-management conference.
An acknowledgement letter from the municipal corporation is not an "honor" but belongs in
Additional Information.

## Additional Information (300 words)

Use it if the 150 characters genuinely cannot carry the work. Not to repeat yourself.

> Jaipur waterlogs in roughly the same places every monsoon. I wanted to know whether
> that was predictable from open data, so I built a model of it.
>
> The model divides the city into 300 m cells and scores each on three things: whether
> terrain causes water to collect there (topographic wetness index, depression depth and
> flow accumulation, computed from NASA elevation data), how much is built there, and
> whether the area shows signs of weaker drainage infrastructure. Everything uses free,
> keyless data so anyone can reproduce it.
>
> Two parts taught me the most. The first was validation. A coloured map looks
> convincing whether or not it is right, so I collected [N] locations from local news
> archives, storm-day reports and my own observations — including places that stayed dry,
> which are harder to find and are what make the test mean anything. The model achieved
> an AUC of [X], meaning that given one flooded and one dry location it ranked the
> flooded one higher [X]% of the time.
>
> The second was discovering my own bug. My first priority list ranked low-lying cells
> with three buildings in them — hydrologically correct, operationally useless. I added
> a minimum-exposure filter and wrote down why.
>
> The model has real limits. At 300 m it cannot see a blocked drain. Its
> socioeconomic layer uses infrastructure proxies rather than income data. And
> OpenStreetMap coverage is uneven in a way that may bias it against the
> under-mapped areas it is meant to help — a problem I have not solved.
>
> Code and map: github.com/YOUR-USERNAME/jaipur-flood-index

Cut the bracketed placeholders and write your real numbers. If you have not validated it,
delete that paragraph rather than inventing a figure.

## If you write the essay about this

Do not write the essay about the code.

The reel this idea came from suggests a "personal connection" paragraph about watching
storms flood poorer districts. **Do not use that paragraph.** It is a template, readers
have seen it, and it is not yours.

What is yours is more specific and more interesting: what happened when you stood at a
junction in Jaipur with a phone and a notebook writing down whether it was flooded, or
what an autorickshaw driver told you about which underpasses he refuses to enter, or the
moment your model confidently ranked an empty field as the city's top priority and you
had to work out why.

The essay is about you, not the project. The project is evidence that the thing you say
about yourself is true.

---

# Part 3 — beyond applications

The most valuable step is also the one almost nobody takes: **send it to someone who
could use it.**

- Jaipur Municipal Corporation (Greater and Heritage) — engineering wing
- Rajasthan State Disaster Management Authority
- Urban planning faculty at MNIT Jaipur

A short, plain email: here is a map, here is how it was built, here is what it cannot do,
does it match what you see on the ground? Ask a question rather than making a claim.

If someone replies, that is worth more than any line on a form. If they tell you the
model is wrong about a specific area, that is worth more still — and it makes the project
genuinely yours in a way no amount of code can.
