# What the evidence says about saving, and what this tool should do about it

Distilled 2026-08-15 from a four-stream research fan-out. Every claim below is
tagged with how it was checked:

- **[verified]** — primary source fetched and read during this session
- **[cross-confirmed]** — two or more independent research streams reported the
  same figures from the same primary source
- **[single-source]** — one stream reported it; not independently checked
- **[retracted]** — was reported to me and later withdrawn; do not use

One research stream fabricated a section by writing up sub-agent findings that
never arrived, and retracted it. That is why the tags exist. Anything not tagged
`verified` or `cross-confirmed` should be re-checked before it is repeated in
public.

---

## 1. The problem is returning, not finding

**Re-finding already works.** A personal-information-management study (keeping
n=24, re-finding n=12, survey n=214) measured people relocating things they had
saved: **90% success for low-frequency sites, 100% for high-frequency, average
under one minute, 93% succeeding with the first method they tried.**
[cross-confirmed]

**Saving does not help you come back.** Bergman, Whittaker & Schooler (2021),
*J. Librarianship & Information Science*, doi:10.1177/0961000620949652 — 50
participants, 250 bookmarked retrieval targets:

- only **41 (16%)** were ever retrieved using the bookmark facility
- only **9 (4%)** came through the bookmarks menu hierarchy; the rest came off
  the permanently visible toolbar
- **bookmarked sites were not re-found better than sites merely visited before**

[cross-confirmed]

**Filing removes the reminder, which was the whole function.** Barreau & Nardi
(1995), *SIGCHI Bulletin* 27(3):39–43 — people prefer location-based finding
*because it reminds them*, avoid elaborate filing, and archive little.
[cross-confirmed]

**Consequence for this tool: a better search box would be building for a
phantom.** A `/find` command was designed and cancelled on this evidence.

---

## 2. Statistics about bookmarking that are fabricated

Chased to ground and found to have no primary source. Do not repeat these:

| Claim | Reality |
|---|---|
| "90% of saved articles are never read" | No source. Pocket and Instapaper never published a read-through rate. [cross-confirmed] |
| "~70% of saved links are never revisited" | Traced to a blog citing nothing. [cross-confirmed] |
| "X users bookmark 65 million times a day" | A *user's* claim that Musk replied to, not an X statistic. [cross-confirmed] |
| "29% of Instagram users save posts weekly" | Stat-compilation page, no methodology. [cross-confirmed] |
| "The average saved article has a 37-day lifespan" | A *Fast Company* piece describing one single article. [single-source] |
| "Digital amnesia" | Coined in a **Kaspersky Lab press release, 1 July 2015** — a 1,000-person self-report survey with no memory test, no control group, never peer reviewed, ending in a pitch for antivirus software. [single-source, but the press release is explicit] |

The defensible number is Bergman's **16%**.

---

## 3. The popular neuroscience is mostly wrong

**"Google makes you forget" failed replication — twice.** Sparrow, Liu & Wegner
(2011), *Science* 333:776, is the source of the entire genre.

- Camerer et al. (2018), *Nature Human Behaviour*, Social Sciences Replication
  Project: original reported a **121ms** effect; pooled replication at **N=234**
  found **2.89ms**, p=.449. One of the 8 of 21 studies that failed. [single-source]
- Hesselmann et al. (2020), *PeerJ* 8:e10325 — preregistered, **N=117 (89
  analysed)**, built specifically around Sparrow's own published objections.
  **t(88) = −1.04, p = .301, BF01 = 5.07.** Authors: *"no conclusive evidence in
  favor of the notion that the concept of the Internet... becomes automatically
  activated."* **[verified — fetched from PMC7651475]**

**The Zeigarnik effect does not hold for memory.** Ghibellini & Meier (2025),
*Humanities and Social Sciences Communications* 12:962,
doi:10.1057/s41599-025-05000-w — meta-analysis. Excluding Zeigarnik's own 1927
study, the interrupted-to-completed recall ratio is **0.99**, with interrupted
tasks making up **49.16%** of recalled tasks. No advantage at all.
**[verified]** The *Ovsiankina* effect — the tendency to **resume** an
interrupted task — does replicate. Open loops pull at behaviour; they do not
improve memory.

**There is no neuroscience of bookmarking.** No fMRI, EEG or structural study of
saving, bookmarking or screenshotting exists. The one EEG study that looked for
a neural signature of saving (Runge et al. 2021, *Eur J Neurosci*, N=52) **found
none**. [single-source]

**"Collector's fallacy" is a blog coinage** — Christian Tietze, zettelkasten.de,
20 January 2014, which performs the coinage in its own text. No measure, no
experimental literature. The intuition is better supported under other names:
the illusion of explanatory depth (Rozenblit & Keil 2002) and search-inflated
self-assessed knowledge (Fisher, Goddu & Keil 2015, nine experiments; Ward 2021,
*PNAS*, eight experiments, n=1,917). [single-source]

**What survives:** offloading reduces what you encode *when you expect the store
to be available*, and the cost is an effort-and-expectation effect rather than
evidence of any brain change. And saving cuts both ways — Storm & Stone (2015)
found saving one file **improves** memory for the next, replicated at about half
the original magnitude (Flusberg & Ramos 2018, N=50, d=0.47). Offloading is a
reallocation, not a deletion. [single-source]

---

## 4. What actually works: retrieval, not re-exposure

This is the strongest evidence in the whole review.

**Roediger & Karpicke (2006), *Psych Science* 17(3):249–255**, N=120: at 5
minutes restudying wins (81% vs 75%); **at one week testing wins 56% vs 42%**.
The condition that felt best predicted best and performed worst. [verified]

**Karpicke & Blunt (2011), *Science* 331:772–775** — retrieval practice vs
elaborative concept mapping, one-week delay:

- Exp 1 (N=80): retrieval **M=.67** vs concept mapping **M=.45**, **d=1.50**
- Exp 2 (N=120): **d=1.07** on short answer, and **d=1.01 even when the final
  test was building a concept map**
- **101/120 (84%) did better after retrieval; 90/120 (75%) predicted the
  opposite**

[cross-confirmed — three streams reported identical figures]

**And it replicated.** Karpicke & Blunt was in the *same* Social Sciences
Replication Project that Sparrow failed, and it passed at stage 1.
[single-source, but the contrast is worth knowing]

**Meta-analytic size:** Rowland (2014), *Psych Bulletin* 140(6):1432–1463 —
k=159, **g=0.50 [0.42, 0.58]**, 93% of effect sizes positive. Feedback nearly
doubles it (**0.73 with vs 0.39 without**). Delay matters: **≥1 day g=0.69 vs
<1 day g=0.41**. Harder retrieval helps more — free recall 0.81 > cued 0.72 >
recognition 0.36. [verified]

**Dunlosky et al. (2013), *PSPI* 14(1):4–58** rated ten study techniques:

| Utility | Technique |
|---|---|
| **HIGH** | Practice testing, distributed practice |
| MODERATE | Elaborative interrogation, self-explanation, interleaved practice |
| **LOW** | Summarization, **highlighting**, keyword mnemonic, imagery, **rereading** |

[cross-confirmed]

### The honest ceiling

**Yang et al. (2021), *Psych Bulletin* 147(4):399–435** — 222 studies, 48,478
students, real classrooms. Overall **g=0.499**, but broken down by what testing
was compared against:

- vs doing nothing: **g=0.610**
- vs **restudying**: **g=0.330**
- vs **other elaborative strategies**: **g=0.095, p=.062 — not significant**

[single-source, but internally consistent and reported with CIs]

**"Retrieval beats everything" is overstated.** The large numbers come from
comparisons against doing nothing. Against other active strategies it is a wash.

Also note **Karpicke & Roediger (2008)'s famous d=4.03** is a paradigm
demonstration, not an estimate of what a product can deliver. [verified]

---

## 5. Three design rules the evidence actually supports

**a) The system writes the question; the user writes the answer.**

Myers, Hausman & Rhodes (2024), *JEP: Applied* 30(2):241–257,
doi:10.1037/xap0000487 — participants who wrote and answered their own questions
got **no benefit**, and tended to do **worse** than other conditions, because
self-generated questions target the wrong material. **[verified that the paper
and design exist; the effect direction is single-source]**

Same direction from highlighting: Ponce, Mayer & Méndez (2022), 36 studies —
**instructor-provided highlighting d=0.44** (helps memory *and* comprehension)
vs **learner-generated d=0.36 memory / 0.20 comprehension**, and **inappropriate
highlighting d=−0.70**. [single-source]

The generation effect (d=0.40, Bertsch et al. 2007, 445 effect sizes) is about
generating the **answer**, not authoring the **prompt**. [cross-confirmed]

**b) Ask higher-order questions, not "what did it say".**

Hamaker (1986) — factual questions help you on the repeated fact; higher-order
questions generalise to related *and unrelated* higher-order items. Pan &
Rickard (2018), 192 effect sizes, N=10,382 — transfer is **d=0.40** overall, but
without response congruency and elaborated retrieval the bias-corrected
intercept is **≈0.015, effectively zero**. [single-source]

**c) Schedule loosely and err long.**

Cepeda et al. (2008/2009): the penalty for too *short* a gap is far larger than
for too *long* a gap — a gap 6–14× longer than optimal cost 11–23% and was not
statistically significant, while a too-short gap cost 34–60% of the achievable
gain. Expanding intervals are **not** better than uniform ones (Latimier et al.
2021, g=0.034, n.s.). [single-source — one stream declined to verify these
numbers at all, so treat the specific figures as provisional; the *direction*
was reported by both]

**Do not interleave across topics.** Brunmair & Richter (2019), 59 studies,
N=8,466: interleaving is **non-significant for expository text** and
**negative for words (g=−0.39)**. Interleaving is for discriminating confusable
categories, not for variety. [single-source]

---

## 6. What the competition actually ships

**Readwise's Daily Review is not spaced repetition.** From their own docs,
verbatim:

> "If you have 500 total highlights in your account and a single document
> contains 100 highlights, there's a 20% chance your Daily Review will contain a
> highlight from that book... Each time a highlight is shown, its probability of
> resurfacing is significantly decreased."

That is **weighted random sampling proportional to document size, with a recency
penalty**. No memory model, no grading, no intervals. Their opt-in *Mastery*
layer is a decaying recall-probability half-life (**7 / 14 / 28 days**,
resurfacing at **≤50%**), which is closer — but the default experience is
re-exposure to text you already highlighted. **[verified — fetched from
docs.readwise.io]**

In Dunlosky's terms **the default Daily Review is rereading, the low-utility
technique, wearing retrieval practice's vocabulary.**

**Nobody in the read-later category ships retrieval at all.** Matter has no
resurfacing (it exports highlights *to* Readwise). Karakeep — 28k stars — has
zero issues or discussions matching "spaced repetition", "resurface" or "daily
digest". Instapaper has manual shuffle only. Glasp markets a "randomly selected"
daily email as spaced repetition. [single-source]

---

## 7. The thing nobody has measured

**Adherence.** No read-later app has ever published a daily-review completion
rate, retention curve, or churn figure. The largest spaced-repetition dataset on
earth (`anki-revlogs-10k`) samples only collections with 5,000+ reviews — a
survivorship filter that deletes exactly the population of interest. No
peer-reviewed study of Pocket, Instapaper or Readwise log data exists.
[single-source]

The universal failure story in user reports is **backlog → dread → abandonment**,
and the design thesis worth stealing came from a commenter:

> "Maximising adherence (and therefore not giving up) is far more important than
> squeezing out a 1% more efficient SRS algorithm"

Which is why the schedule should be loose, the daily volume small, and the
backlog incapable of accumulating.

---

## 8. What this means for saved-to-notes

1. **Don't build search.** Re-finding is solved; returning is not.
2. **Don't build a resurfacing feed.** Re-showing the note is rereading — the
   low-utility technique, and exactly what the market leader actually does.
3. **Build retrieval.** Ask one question about a note the user saved weeks ago,
   let them answer, *then* reveal the note. That is the single evidence-backed
   move available, and nothing in the category ships it.
4. **The tool writes the question.** The user must not author their own prompts.
5. **Higher-order questions** ("how does this connect to X", "when would this
   fail") over factual recall.
6. **Loose, long intervals.** A fixed ladder is defensible; FSRS-grade precision
   is a rounding error next to whether the user shows up.
7. **Cap the daily volume and never accumulate a backlog.** Adherence is the
   entire game.
8. **Be honest in public about the ceiling.** vs other active strategies the
   effect is g=0.095, not significant. The win is over *doing nothing*, which is
   what a bookmark folder currently is.
