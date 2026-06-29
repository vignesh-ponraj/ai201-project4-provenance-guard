# Provenance Guard

A backend a creative-sharing platform plugs into to classify submitted text as
human- or AI-written, score confidence **honestly**, show readers a plain-language
transparency label, and let creators **appeal** a classification.

The guiding principle is the project's own hint: on a writing platform, **a false
positive (calling a human's work AI) is the worst outcome.** That asymmetry is
baked into the thresholds, the labels, and the appeals path — not bolted on.

> Full design rationale lives in [`planning.md`](planning.md) (written before any
> code). This README covers what was built, how to run it, and the evidence.

---

## Setup & run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env (git-ignored) must contain your Groq key:
echo "GROQ_API_KEY=your_key_here" > .env

python app.py            # serves on http://127.0.0.1:5000
```

> SQLite is built in — no extra install. The DB file `provenance.db` is created
> on first run. If the Groq key is missing, the LLM signal degrades gracefully
> (returns `None`) and the system classifies on the two heuristic signals.

---

## Architecture overview — the path a submission takes

```
POST /submit {text, creator_id}
   │  (passes rate limiter: 10/min, 100/day per IP — else 429)
   ▼
┌──────────────┬──────────────────┬────────────────┐
│  LLM signal  │ Stylometric sig. │ Lexical signal │   3 independent signals,
│ (Groq 70B)   │ (burstiness+TTR) │ (AI tells)     │   each → ai_likelihood 0–1
└──────┬───────┴────────┬─────────┴───────┬────────┘
       └────────────────┼─────────────────┘
                        ▼
        scoring.py  →  p_ai (weighted) + confidence (agreement-aware)
                        ▼
        labels.py   →  attribution tier + reader-facing label text
                        ▼
        SQLite: contents row (status=classified)  +  audit_log event
                        ▼
   Response: {content_id, attribution, confidence, label, signals, p_ai, status}
```

A submission is rate-limited, fanned out to three independent detection signals,
combined into a single `p_ai` and an honest `confidence`, mapped to one of three
transparency labels, persisted with status `classified`, and logged — then
returned. **Appeal flow:** `POST /appeal` flips the content's status to
`under_review`, logs the creator's reasoning beside a snapshot of the original
decision, and confirms receipt (no automated re-classification). The Mermaid
version of both flows is in [`planning.md` → Architecture](planning.md#architecture).

### API reference

| Method & path | Body | Returns |
|---|---|---|
| `POST /submit` | `{text, creator_id}` | `content_id`, `attribution`, `confidence`, `label{tier,band,text}`, `signals{…}`, `p_ai`, `status` |
| `POST /appeal` | `{content_id, creator_reasoning}` | `{content_id, status:"under_review", message}` (404 if id unknown) |
| `GET /log?limit=N` | — | `{entries:[…]}` newest-first audit entries |
| `GET /health` | — | `{status:"ok"}` |

---

## Detection signals (multi-signal pipeline — 3 signals)

All three return the **same contract** — `ai_likelihood ∈ [0,1]` (1.0 = fully
AI-like) — so scoring treats them uniformly. They belong to three genuinely
different families, so a text that fools one can still be caught by another, and
**their disagreement is itself signal** (it drives confidence down → "uncertain").

| Signal | Family | What it measures | Why it differs human vs AI | What it **misses** (blind spot) |
|---|---|---|---|---|
| **1. LLM** (`llama-3.3-70b-versatile` via Groq) | Semantic / holistic | Whether the text *reads* as a specific human voice vs. generic, evenly-hedged AI prose | A 70B model has read vast human + AI text; captures coherence and "voice" no statistic can | Non-deterministic; **biased against formal / non-native-English** human writing; fooled by lightly-edited AI |
| **2. Stylometric burstiness** (pure Python) | Statistical / structural | Sentence-length variation (coefficient of variation) + type-token ratio (vocabulary diversity) | Humans are *bursty* (long sentences beside short) and lexically varied; AI trends uniform | Needs ~40+ words; flags terse / repetitive **human** poetry as AI (mitigated by short-text neutralization) |
| **3. Lexical fingerprint** (pure Python) | Surface / lexical | Density of AI "tell" phrases ("it is important to note", "furthermore"…), sentence-opener diversity, punctuation variety | Instruction-tuned models over-use connective boilerplate and formulaic openers | A human deliberately writing formally trips it; trivially evaded by paraphrase |

> **Signal 3 is the stretch feature — ensemble detection.** The required minimum
> is two signals; Provenance Guard runs **three** and documents the weighting
> below. See [Stretch feature](#stretch-feature-ensemble-3-signal-detection).

**Why this combination:** holistic-semantic (1), statistical-structural (2), and
lexical-surface (3) are independent *families*. No single one is reliable alone,
but their agreement (or lack of it) is far more informative than any one score.

---

## Confidence scoring with uncertainty

### How signals combine into one score

```
p_ai       = 0.6·llm + 0.2·stylometry + 0.2·lexical     # LLM is the most reliable signal
                                                         # (if LLM unavailable, its weight is
                                                         #  redistributed across the other two)

conviction = p_ai if p_ai≥0.5 else 1−p_ai               # how far the score commits, in [0.5,1]
margin     = (conviction − 0.5) / 0.5                    # → [0,1]
agreement  = 1 − min(1, stdev(signals)/0.35)             # signals scatter → toward 0
confidence = agreement · (0.5 + 0.5·margin)              # → [0,1]
```

**`confidence` is deliberately *not* `p_ai`.** `p_ai` is *which direction*;
`confidence` is *how much to trust that direction*. It rewards both a decisive
score **and** signal agreement. So when the three signals disagree, confidence
collapses and the result is forced to **uncertain** — even if `p_ai` alone looked
decisive. That is the project's "represent genuine uncertainty" requirement made
mechanical: a 0.51 produces a meaningfully different label than a 0.95.

### Mapping to labels — asymmetric on purpose

| Attribution | Condition |
|---|---|
| `likely_ai` | `p_ai ≥ 0.62` **and** `confidence ≥ 0.45` |
| `likely_human` | `p_ai ≤ 0.45` **and** `confidence ≥ 0.45` |
| `uncertain` | everything else (the wide middle, **or** any low-confidence / disagreeing case) |

The AI bar (`0.62`, i.e. **0.12 above** the 0.5 fence) sits further from center
than the human bar (`0.45`, only **0.05 below**). **It is harder to be accused of
being AI than to be cleared as human** — the false-positive asymmetry, encoded
directly in the thresholds. Confidence bands shown to readers: `High ≥ 0.66`,
`Medium 0.45–0.65`, `Low < 0.45`.

### How I validated the scores are meaningful

I ran four deliberately chosen inputs (the project's calibration set) spanning the
range and checked each against intuition. Actual system output:

| Input | `p_ai` | `confidence` | signals (llm / style / lexical) | Label |
|---|---|---|---|---|
| **Clearly AI** (formal "paradigm shift" essay) | **0.73** | 0.51 (Medium) | 0.80 / 0.54 / 0.70 | `likely_ai` |
| **Clearly human** (casual ramen review) | **0.10** | 0.88 (High) | 0.10 / 0.12 / 0.10 | `likely_human` |
| **Borderline: formal human** (economics abstract) | 0.68 | 0.14 (Low) | 0.80 / 0.79 / 0.20 | `uncertain` |
| **Borderline: lightly-edited AI** (remote-work musing) | 0.35 | 0.28 (Low) | 0.40 / 0.52 / 0.05 | `uncertain` |

What this demonstrates:

- **Two examples with noticeably different confidence:** the clearly-human case
  scores **`confidence 0.88` (High)** while the lightly-edited-AI case scores
  **`confidence 0.28` (Low)** — the score is not a constant; it tracks genuine
  certainty.
- **The asymmetry works where it matters most.** The *formal-human economics
  abstract* is exactly the dangerous false-positive case: the LLM (0.80) and
  stylometry (0.79) both wrongly lean AI. But the lexical signal disagreed (0.20),
  so **agreement collapsed and the result is `uncertain`, not a false AI
  accusation.** This is the whole system earning its keep.
- All three labels are reachable from realistic inputs.

Reproduce with `python test_calibration.py` (server running).

---

## Transparency label — the three variants (exact text)

The reader-facing label changes with the confidence score. `{Band}` is
`High/Medium/Low`; `{NN%}` is the computed confidence. Verbatim text each variant
displays:

| Variant | Exact label text |
|---|---|
| **High-confidence AI** (`likely_ai`) | `⚠ Likely AI-generated. This content shows strong signs of AI generation. Several independent checks agreed its style and structure closely match AI-written text. Confidence: {Band} ({NN}%). No detector is perfect — if you wrote this yourself, you can appeal this label.` |
| **High-confidence human** (`likely_human`) | `✓ Likely human-written. This content reads as human-written. Our checks found the natural variation and individual style typical of a human author, with no strong signs of AI generation. Confidence: {Band} ({NN}%).` |
| **Uncertain** (`uncertain`) | `❓ Authorship uncertain. We can't confidently say who wrote this. Our checks either disagreed or found only weak signals. Confidence: {Band} ({NN}%). We've labeled it 'uncertain' rather than guess — please treat the result with caution.` |

Rendered examples from the actual runs above:

> **⚠ Likely AI-generated.** This content shows strong signs of AI generation.
> Several independent checks agreed its style and structure closely match
> AI-written text. **Confidence: Medium (51%).** No detector is perfect — if you
> wrote this yourself, you can appeal this label.

> **✓ Likely human-written.** This content reads as human-written. Our checks
> found the natural variation and individual style typical of a human author,
> with no strong signs of AI generation. **Confidence: High (88%).**

> **❓ Authorship uncertain.** We can't confidently say who wrote this. Our checks
> either disagreed or found only weak signals. **Confidence: Low (28%).** We've
> labeled it 'uncertain' rather than guess — please treat the result with caution.

**Design choices:** plain language, zero jargon (no "p_ai" or "stylometry");
confidence shown as both a word *and* a number so it's meaningful to a
non-technical reader; the AI label **explicitly invites appeal** (honoring the
asymmetry); and "uncertain" openly admits the system doesn't know rather than
guessing.

---

## Appeals workflow

A creator who believes they were misclassified sends:

```bash
curl -s -X POST http://127.0.0.1:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-CONTENT-ID", "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."}'
```

The endpoint:
1. Verifies the `content_id` exists (`404` if not).
2. Updates that content's status **`classified` → `under_review`**.
3. Appends an `appeal` event to the audit log carrying the creator's reasoning
   **and a snapshot of the original decision** (attribution, confidence, all three
   signal scores) so a reviewer sees both sides at once.
4. Returns `{content_id, status:"under_review", message}`.

No automated re-classification — a human decides. A reviewer's queue is every
`contents` row where `status = under_review`, joined to its original `classified`
audit event and the new `appeal` event.

---

## Rate limiting

Applied to `POST /submit` via Flask-Limiter (in-memory storage), keyed per client IP:

```python
@limiter.limit("10 per minute;100 per day")
```

| Limit | Value | Reasoning |
|---|---|---|
| Per minute | **10** | A real writer submits their own work occasionally — a poem, a draft, a revision. Ten per minute comfortably covers a human checking a few pieces or re-submitting after edits, while a flood-script firing hundreds of requests is stopped immediately. |
| Per day | **100** | A second, slower ceiling for sustained abuse that stays under the per-minute bar (e.g. a scraper pacing itself at 1/sec). 100/day is far above any genuine single creator's volume but caps a patient adversary — and, since each `/submit` costs a Groq LLM call, it also protects the free-tier API budget from being drained. |

The two limits cover two distinct threat shapes: **bursty** flooding (per-minute)
and **slow-drip** abuse (per-day).

### Evidence — rate limit triggers

12 rapid requests against a fresh server (limit 10/min):

```
req  1 -> 200      req  7 -> 200
req  2 -> 200      req  8 -> 200
req  3 -> 200      req  9 -> 200
req  4 -> 200      req 10 -> 200
req  5 -> 200      req 11 -> 429   ← limit hit
req  6 -> 200      req 12 -> 429
```
Body of a 429 response: `429 Too Many Requests — 10 per 1 minute`.

---

## Audit log

Every classification and every appeal is written as a structured, immutable event
to the SQLite `audit_log` table. Each entry records timestamp, content id,
attribution, combined confidence, **all three individual signal scores**, the
status, and (for appeals) the creator's reasoning beside the original decision.
Surface it with `GET /log`.

Sample (`GET /log?limit=10`) — **5 entries: 1 appeal + 4 classifications**:

```json
{
  "entries": [
    {
      "event_type": "appeal",
      "content_id": "9f0fdb93-a5d0-44db-a276-f2e409335392",
      "timestamp": "2026-06-29T02:23:18.292746Z",
      "status": "under_review",
      "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
      "original_decision": {
        "attribution": "likely_ai", "confidence": 0.5099, "p_ai": 0.7289,
        "llm_score": 0.8, "style_score": 0.5444, "lexical_score": 0.7
      }
    },
    {
      "event_type": "classified",
      "content_id": "51aa48cd-1427-482a-905f-57dd095eeb2a",
      "creator_id": "test-BORDERLINE-edited-AI",
      "timestamp": "2026-06-29T02:22:36.373686Z",
      "attribution": "uncertain", "confidence": 0.2809, "p_ai": 0.3532,
      "llm_score": 0.4, "style_score": 0.5158, "lexical_score": 0.05,
      "status": "classified", "used_signals": ["llm","stylometry","lexical"]
    },
    {
      "event_type": "classified",
      "content_id": "2bf0c51a-38f6-469c-a16d-31825073a066",
      "creator_id": "test-BORDERLINE-formal-human",
      "timestamp": "2026-06-29T02:22:21.000000Z",
      "attribution": "uncertain", "confidence": 0.1351, "p_ai": 0.6778,
      "llm_score": 0.8, "style_score": 0.7888, "lexical_score": 0.2,
      "status": "classified", "used_signals": ["llm","stylometry","lexical"]
    },
    {
      "event_type": "classified",
      "content_id": "bd7a8c6f-d081-471f-805f-c2563df7448f",
      "creator_id": "test-CLEARLY-HUMAN",
      "attribution": "likely_human", "confidence": 0.8779, "p_ai": 0.1031,
      "llm_score": 0.1, "style_score": 0.1157, "lexical_score": 0.1,
      "status": "classified", "used_signals": ["llm","stylometry","lexical"]
    },
    {
      "event_type": "classified",
      "content_id": "9f0fdb93-a5d0-44db-a276-f2e409335392",
      "creator_id": "test-CLEARLY-AI",
      "attribution": "likely_ai", "confidence": 0.5099, "p_ai": 0.7289,
      "llm_score": 0.8, "style_score": 0.5444, "lexical_score": 0.7,
      "status": "classified", "used_signals": ["llm","stylometry","lexical"]
    }
  ]
}
```

---

## Stretch feature: ensemble 3-signal detection

The required minimum is two signals; Provenance Guard runs **three** with a
documented **weighted-average** ensemble (`scoring.py`):

```
p_ai = 0.6·LLM + 0.2·stylometry + 0.2·lexical
```

The LLM carries the most weight because it cleanly separates the calibration set
(~0.8 AI vs ~0.1 human) where the heuristics are noisier. The two heuristics serve
double duty: they nudge the score **and** their spread feeds the `agreement` term,
so the third signal materially changes outcomes — in the formal-human case it was
the lexical signal's disagreement that (correctly) pulled the result back to
`uncertain` instead of a false AI accusation. The weighting auto-renormalizes if
the LLM signal is unavailable, so the ensemble degrades to two signals rather than
breaking.

---

## Known limitations

- **Formal or non-native-English human writing is the system's hardest case.**
  An academic abstract or an ESL author's careful, even-toned prose has low
  sentence-length variation and formal connectives — properties the stylometric
  *and* lexical signals read as "AI", and that the LLM signal is independently
  biased to over-flag. In the calibration set the economics abstract pushed two of
  three signals toward AI. The system avoids a confident false positive *only*
  because the third signal disagreed; a formal human text where all three happen
  to align would be mislabeled. This is intrinsic to what the signals measure, not
  a data-volume problem — which is exactly why the asymmetric thresholds and the
  appeal path exist as the safety net rather than relying on detection alone.
- **Short text (< ~40 words):** sentence-variance and TTR are unstable, so
  stylometry self-reports `reliable: false` and pulls its score halfway to neutral
  — meaning very short pieces lean toward `uncertain` by design.
- **Adversarial paraphrase / "humanizer" tools** can flatten the lexical tells and
  raise burstiness, defeating the heuristics; the LLM signal is more robust but
  not immune. Perfect AI detection is unsolved — the honest design goal here is
  calibrated uncertainty plus a creator's right to appeal, not certainty.

---

## Spec reflection

- **Where the spec helped:** writing out the three label variants *and the
  asymmetric-threshold rationale* in `planning.md` before any code gave the
  scoring logic a concrete target. When calibration broke (clearly-AI text landing
  in `uncertain`), I didn't have to guess what "correct" meant — the spec already
  said *clearly-AI must reach `likely_ai`* and *a formal human must not be falsely
  accused*. That turned a vague "scores feel off" into a specific, testable fix.
- **Where the implementation diverged:** `planning.md §2` originally specified
  `AI_THRESHOLD=0.70 / HUMAN=0.40 / MIN_CONFIDENCE=0.55` with
  `confidence = decisiveness·(0.5+0.5·agreement)`. Testing exposed that this
  combination makes `likely_ai` **mathematically unreachable** — at `p_ai=0.70`,
  `decisiveness=0.4`, so confidence caps at 0.4, below the 0.55 gate. I diverged:
  rebalanced weights toward the LLM (0.6), lowered the thresholds to
  `0.62 / 0.45 / 0.45`, and changed confidence to `agreement·(0.5+0.5·margin)`.
  The *spirit* of the spec (asymmetry, disagreement→uncertain) was preserved; the
  exact numbers changed because only running it revealed the contradiction.
  `planning.md` documents the original intent; `config.py` is the source of truth
  for the shipped values.

---

## AI usage

1. **Stylometry signal + first scoring draft.** I gave the assistant
   `planning.md §1–§2` and asked it to implement the stylometric signal and the
   confidence combiner. It produced a type-token-ratio mapping that assumed AI
   text sits in a mid 0.4–0.6 TTR band and treated *high* TTR as strong evidence
   of "human." On short, dense text TTR is naturally high regardless of author, so
   the canonical clearly-AI essay got dragged toward "human" and mislabeled
   `uncertain`. **I overrode it:** made sentence-length burstiness the primary
   metric (recalibrated to cv 0.25→0.65), cut TTR's weight to 0.25, and added
   short-text neutralization that pulls unreliable scores halfway to 0.5.
2. **Confidence formula vs. the spec thresholds.** I asked the assistant to make
   the scoring match the thresholds I'd written in `planning.md`. It faithfully
   implemented `confidence = decisiveness·(0.5+0.5·agreement)` against
   `AI_THRESHOLD=0.70` / `MIN_CONFIDENCE=0.55` — *exactly as written* — which is
   how I discovered the spec itself was internally inconsistent (that pairing makes
   `likely_ai` unreachable). I caught it by running the four calibration inputs and
   seeing clearly-AI never reach the AI label, then **revised both the formula and
   the thresholds** (see [Spec reflection](#spec-reflection)). Lesson applied:
   verify generated scoring against real inputs, not just against the spec it was
   told to follow.

---

## Project layout

```
app.py                 Flask API: /submit, /appeal, /log, /health + rate limiting
config.py              weights, thresholds, rate limits — single source of truth
db.py                  SQLite: contents (mutable status) + audit_log (append-only)
llm_signal.py          Signal 1 — Groq holistic read (degrades gracefully)
stylometry_signal.py   Signal 2 — burstiness + type-token ratio (pure Python)
lexical_signal.py      Signal 3 — AI tell-phrases / openers / punctuation (stretch)
scoring.py             p_ai + confidence + asymmetric attribution
labels.py              the three transparency-label variants
audit.py               structured event logging for classifications & appeals
test_calibration.py    submits the 4 calibration inputs and prints scores
planning.md            pre-implementation spec + Mermaid architecture diagram
```
