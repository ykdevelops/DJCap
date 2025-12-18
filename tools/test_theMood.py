import json
import sys

import requests


def main() -> None:
    payload = {
        "artist": "The Weeknd",
        "title": "Blinding Lights",
        "max_keywords": 18,
        "max_scene_sentences": 2,
    }

    r = requests.post("http://localhost:8080/api/theMood", json=payload, timeout=90)
    print("status:", r.status_code)
    print(r.text[:2000])
    r.raise_for_status()

    data = r.json()
    # Minimal structural assertions
    assert "track" in data and "genres" in data and "theMood" in data
    assert "primary" in data["track"] and "secondary" in data["track"]
    assert isinstance(data["genres"], list)

    kw = data["theMood"]["keywords"]
    ev = data["theMood"]["evidence_phrases"]
    assert isinstance(kw, list) and 6 <= len(kw) <= payload["max_keywords"]
    assert isinstance(ev, list) and len(ev) >= 3

    # Ensure strict JSON-serializable output
    json.dumps(data)
    print("OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FAILED:", e)
        sys.exit(1)


