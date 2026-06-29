# Portfolio Walkthrough — Script & Commands (~2–3 min)

A short, unpolished tour showing Provenance Guard working end-to-end. Keep it
casual: show it running, narrate a few design decisions. Detailed evidence lives
in the README — this is just the tour.

## Before you hit record (one-time setup)

```bash
cd ai201-project4-provenance-guard
python -m venv .venv && source .venv/bin/activate   # if not already created
pip install -r requirements.txt                     # if not already installed
# .env must contain GROQ_API_KEY=... (already set locally; never committed)
```

Recording tips:
- Bump your terminal font size (so it's readable on video).
- Use **two terminal panes**: left = server logs, right = where you run commands.
- Every response is piped through `python -m json.tool` so it's pretty on screen.
- Have this file open to copy from.

### Start the server (left pane)

This kill-by-port guard avoids the macOS "AirPlay/stale server on :5000" gotcha:

```bash
source .venv/bin/activate
for pid in $(lsof -nP -iTCP:5000 -sTCP:LISTEN -t 2>/dev/null); do \
  ps -p $pid -o comm= | grep -qi python && kill -9 $pid; done
rm -f provenance.db        # fresh DB so the demo dataset is clean
python app.py              # leave this running; watch the [CLASSIFIED]/[APPEAL] logs
```

Everything below runs in the **right pane**. Keep a shell variable handy for the
content_id you'll appeal:

---

## Beat 1 — What it is (15s, talking head / over the editor)

> "This is Provenance Guard — a backend a writing platform plugs in to tell
> whether submitted text was written by a human or AI. The key design principle:
> on a creative platform, **falsely accusing a human is the worst outcome**, so
> the whole system is tuned to be cautious and to give creators a way to appeal."

Optionally show the architecture diagram in `planning.md`.

---

## Beat 2 — The three transparency labels (45s) ⭐ the core

Narrate: "Three signals — an LLM, plus two pure-Python heuristics — combine into a
confidence score that drives one of three labels."

**Likely human** (casual writing):
```bash
curl -s -X POST http://127.0.0.1:5000/submit -H "Content-Type: application/json" \
  -d '{"text":"ok so i finally tried that ramen place downtown and honestly? underwhelming. broth was fine but WAY too much sodium and i was thirsty for hours. probably wont go back unless dragged.","creator_id":"alice"}' \
  | python -m json.tool
```
→ point at `"attribution": "likely_human"` and the **High** confidence label text.

**Likely AI** (generic essay) — save its `content_id` for the appeal:
```bash
RESP=$(curl -s -X POST http://127.0.0.1:5000/submit -H "Content-Type: application/json" \
  -d '{"text":"Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders must collaborate to ensure responsible deployment.","creator_id":"frank"}')
echo "$RESP" | python -m json.tool
CID=$(echo "$RESP" | python -c "import json,sys;print(json.load(sys.stdin)['content_id'])")
echo "Saved content_id for appeal: $CID"
```
→ point at `"attribution": "likely_ai"` and the **⚠** label that *invites appeal*.

**Uncertain** (formal human abstract — signals disagree):
```bash
curl -s -X POST http://127.0.0.1:5000/submit -H "Content-Type: application/json" \
  -d '{"text":"The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between price stability and the unintended consequences of prolonged low interest rates on valuations.","creator_id":"grace"}' \
  | python -m json.tool
```
> "This formal human writing fools two of the three signals — but the third
> disagrees, so confidence collapses and we say **uncertain** instead of falsely
> calling it AI. That disagreement-driven caution is the whole point."

---

## Beat 3 — Appeals (20s)

> "Any creator who thinks they were misclassified can appeal."
```bash
curl -s -X POST http://127.0.0.1:5000/appeal -H "Content-Type: application/json" \
  -d "{\"content_id\":\"$CID\",\"creator_reasoning\":\"I wrote this myself. I'm a non-native English speaker so my style reads formal.\"}" \
  | python -m json.tool
```
→ status flips to `under_review`. Mention it's logged beside the original decision.

---

## Beat 4 — Stretch: multi-modal + verified-human (30s)

> "I extended the same pipeline to a second content type — image metadata."

**AI-generated image:**
```bash
curl -s -X POST http://127.0.0.1:5000/submit -H "Content-Type: application/json" \
  -d '{"content_type":"image_metadata","creator_id":"bob","metadata":{"software":"Midjourney v6","prompt":"a cat astronaut, cinematic"}}' \
  | python -m json.tool
```
→ `likely_ai`. Then a **real photo** (rich EXIF) → `likely_human`:
```bash
curl -s -X POST http://127.0.0.1:5000/submit -H "Content-Type: application/json" \
  -d '{"content_type":"image_metadata","creator_id":"carol","metadata":{"camera_make":"Canon","camera_model":"EOS R6","iso":400,"exposure_time":"1/200","f_number":2.8,"lens_model":"RF50","gps":{"lat":1}}}' \
  | python -m json.tool
```

**Verified-human credential** (two-step challenge):
```bash
START=$(curl -s -X POST http://127.0.0.1:5000/verify/start -H "Content-Type: application/json" -d '{"creator_id":"dave"}')
echo "$START" | python -m json.tool
CH=$(echo "$START" | python -c "import json,sys;print(json.load(sys.stdin)['challenge_id'])")
curl -s -X POST http://127.0.0.1:5000/verify/complete -H "Content-Type: application/json" \
  -d "{\"challenge_id\":\"$CH\",\"typed_phrase\":\"I am a human creator and this is my original work\"}" \
  | python -m json.tool
```
> "Now dave is a Verified Human Creator — but notice the credential is about
> *identity*, not a claim about any one post. If a verified human's text still
> reads as AI, it's flagged anyway, and that's exactly a strong appeal case."

---

## Beat 5 — Audit log + analytics dashboard (20s)

```bash
curl -s "http://127.0.0.1:5000/log?limit=5" | python -m json.tool        # structured trail
curl -s http://127.0.0.1:5000/analytics | python -m json.tool            # metrics JSON
```
Then open the HTML dashboard in a browser:
```bash
open http://127.0.0.1:5000/dashboard
```
→ show the AI / human / uncertain breakdown, appeal rate, avg confidence.

---

## Beat 6 — Rate limiting (20s) — DO THIS LAST, on a fresh server

In the **left pane**, restart the server to reset the in-memory limiter counter
(say this out loud — it's why the burst starts clean):
```bash
# Ctrl-C the running server, then:
python app.py
```
In the **right pane**, fire 12 rapid requests (limit is 10/min):
```bash
for i in $(seq 1 12); do
  printf "req %2d -> " "$i"
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text":"rate limit test","creator_id":"flooder"}'
done
```
→ first **10 return 200**, then **429**. 
> "10 per minute, 100 per day — enough for a real writer revising their work,
> but it shuts down a flood script immediately and protects the Groq API budget."

---

## Beat 7 — Wrap (10s)

> "So: multi-signal detection, honest confidence that admits uncertainty, a
> plain-language label, an appeal path, rate limiting, and a full audit log —
> plus multi-modal, a verified-human credential, and an analytics dashboard.
> Perfect AI detection is unsolved, so the real engineering goal here was to be
> *honest about uncertainty* and to never quietly accuse a human. Thanks!"

---

### Quick reference — full demo order (copy/paste friendly)
1. Start server (fresh DB)
2. Beat 2: human → AI (save `$CID`) → uncertain
3. Beat 3: appeal `$CID`
4. Beat 4: AI image → real photo → verify dave
5. Beat 5: `/log`, `/analytics`, open `/dashboard`
6. **Restart server**, then Beat 6: rate-limit burst
