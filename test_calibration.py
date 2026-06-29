"""Calibration harness — submits 4 deliberately chosen inputs spanning the
confidence range and prints the scores (Milestone 4 verification).
Run with the server up: python test_calibration.py
"""
import json
import urllib.request

BASE = "http://127.0.0.1:5000"

CASES = [
    ("CLEARLY-AI",
     "Artificial intelligence represents a transformative paradigm shift in modern "
     "society. It is important to note that while the benefits of AI are numerous, it "
     "is equally essential to consider the ethical implications. Furthermore, "
     "stakeholders across various sectors must collaborate to ensure responsible "
     "deployment."),
    ("CLEARLY-HUMAN",
     "ok so i finally tried that new ramen place downtown and honestly? underwhelming. "
     "the broth was fine but they put WAY too much sodium in it and i was thirsty for "
     "like three hours after. my friend got the spicy version and said it was better. "
     "probably won't go back unless someone drags me there"),
    ("BORDERLINE-formal-human",
     "The relationship between monetary policy and asset price inflation has been "
     "extensively studied in the literature. Central banks face a fundamental tension "
     "between their mandate for price stability and the unintended consequences of "
     "prolonged low interest rates on equity and real estate valuations."),
    ("BORDERLINE-edited-AI",
     "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
     "flexibility and no commute on one side, isolation and blurred work-life "
     "boundaries on the other. Studies show productivity varies widely by individual "
     "and role type."),
]


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


if __name__ == "__main__":
    ids = []
    for name, text in CASES:
        d = post("/submit", {"text": text, "creator_id": f"test-{name}"})
        sig = {k: v["ai_likelihood"] for k, v in d["signals"].items()}
        print(f"\n===== {name} =====")
        print(f"  attribution : {d['attribution']}")
        print(f"  confidence  : {d['confidence']}   p_ai: {d['p_ai']}")
        print(f"  signals     : {sig}")
        print(f"  label       : {d['label']['text']}")
        print(f"  content_id  : {d['content_id']}")
        ids.append(d["content_id"])
    # stash the first id for the appeal test
    with open("last_content_id.txt", "w") as f:
        f.write(ids[0])
