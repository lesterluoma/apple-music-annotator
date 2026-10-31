#!/usr/bin/env python3
"""Local web UI for bulk-editing Apple Music track metadata.

Run:  python3 server.py   then open http://localhost:8737
"""
import json
import re
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JXA_DIR = ROOT / "jxa"
DATA_DIR = ROOT / "data"
LIBRARY_CACHE = DATA_DIR / "library.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
INDEX_HTML = ROOT / "static" / "index.html"
PORT = 8737

# Key spellings already used in the library's comments, with their Open Key codes.
KEYS = {
    "C major": "1d", "G major": "2d", "D major": "3d", "A major": "4d",
    "E major": "5d", "B major": "6d", "F# major": "7d", "D♭ major": "8d",
    "A♭ major": "9d", "E♭ major": "10d", "B♭ major": "11d", "F major": "12d",
    "A minor": "1m", "E minor": "2m", "B minor": "3m", "F# minor": "4m",
    "C# minor": "5m", "G# minor": "6m", "E♭ minor": "7m", "B♭ minor": "8m",
    "F minor": "9m", "C minor": "10m", "G minor": "11m", "D minor": "12m",
}
KEY_RE = re.compile(r"^([A-G][♭♯b#]?\s+(?:major|minor))\s+\(\d{1,2}[md]\)")

write_lock = threading.Lock()
library = {}  # persistentID -> track dict
loaded_at = 0.0


def run_jxa(script, *args):
    proc = subprocess.run(
        ["osascript", "-l", "JavaScript", str(JXA_DIR / script), *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"{script} failed")
    return json.loads(proc.stdout)


def parse_key(comment):
    m = KEY_RE.match(comment or "")
    return m.group(1) if m else ""


def to_track(row):
    rating = 0 if row["ratingKind"] == "computed" else row["rating"]
    return {
        "id": row["persistentID"],
        "name": row["name"],
        "artist": row["artist"],
        "albumArtist": row["albumArtist"],
        "album": row["album"],
        "genre": row["genre"],
        "bpm": row["bpm"],
        "year": row["year"],
        "rating": rating // 20,
        "grouping": row["grouping"],
        "comment": row["comment"],
        "key": parse_key(row["comment"]),
        "trackNumber": row["trackNumber"],
        "discNumber": row["discNumber"],
        "duration": row["duration"],
        "unavailable": row["cloudStatus"] == "no longer available",
    }


def refresh_library():
    global library, loaded_at
    cols = run_jxa("read_library.js")
    names = list(cols)
    rows = [dict(zip(names, values)) for values in zip(*cols.values())]
    library = {t["id"]: t for t in map(to_track, rows)}
    loaded_at = time.time()
    save_library()


def save_library():
    DATA_DIR.mkdir(exist_ok=True)
    LIBRARY_CACHE.write_text(json.dumps({"loadedAt": loaded_at, "tracks": list(library.values())}))


def load_library():
    global library, loaded_at
    if LIBRARY_CACHE.exists():
        data = json.loads(LIBRARY_CACHE.read_text())
        library = {t["id"]: t for t in data["tracks"]}
        loaded_at = data["loadedAt"]
    else:
        refresh_library()


def validate_fields(fields):
    """Convert UI field values into Music property values for apply_edits.js."""
    out = {}
    for field, value in fields.items():
        if field in ("genre", "grouping"):
            out[field] = str(value).strip()
        elif field in ("bpm", "year"):
            value = int(value or 0)
            if not 0 <= value <= (999 if field == "bpm" else 9999):
                raise ValueError(f"{field} out of range: {value}")
            out[field] = value
        elif field == "rating":
            value = int(value or 0)
            if not 0 <= value <= 5:
                raise ValueError(f"rating out of range: {value}")
            out[field] = value * 20
        elif field == "key":
            if value and value not in KEYS:
                raise ValueError(f"unknown key: {value}")
            out[field] = f"{value} ({KEYS[value]})" if value else ""
        else:
            raise ValueError(f"field not editable: {field}")
    return out


def apply_edits(edits):
    """Run edits through Music, update the cache, and return per-track results."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(edits, f)
    try:
        results = run_jxa("apply_edits.js", f.name)
    finally:
        Path(f.name).unlink()
    for result in results:
        track = library.get(result["id"])
        if not track:
            continue
        for change in result["changes"]:
            value = change["new"]
            if change["field"] == "rating":
                value //= 20
            track[change["field"]] = value
            if change["field"] == "comment":
                track["key"] = parse_key(value)
    save_library()
    return results


def record_batch(label, results, undoes=None):
    changes = [
        {"id": r["id"], **c} for r in results if r["ok"] for c in r["changes"]
    ]
    batch = {
        "batchId": uuid.uuid4().hex[:12],
        "time": time.time(),
        "label": label,
        "changes": changes,
        "undoes": undoes,
    }
    DATA_DIR.mkdir(exist_ok=True)
    with HISTORY_FILE.open("a") as f:
        f.write(json.dumps(batch) + "\n")
    return batch


def read_history():
    if not HISTORY_FILE.exists():
        return []
    return [json.loads(line) for line in HISTORY_FILE.read_text().splitlines() if line]


def summarize(results):
    failed = [r for r in results if not r["ok"]]
    return {
        "tracksChanged": sum(1 for r in results if r["ok"] and r["changes"]),
        "failed": [{"id": r["id"], "error": r["error"]} for r in failed],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/":
            body = INDEX_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/library":
            self.send_json({"loadedAt": loaded_at, "keys": list(KEYS), "tracks": list(library.values())})
        elif self.path == "/api/history":
            history = read_history()
            undone = {b["undoes"] for b in history if b.get("undoes")}
            for b in history:
                b["undone"] = b["batchId"] in undone
            self.send_json(list(reversed(history))[:200])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self.read_json()
            with write_lock:
                if self.path == "/api/refresh":
                    refresh_library()
                    self.send_json({"loadedAt": loaded_at, "count": len(library)})
                elif self.path == "/api/apply":
                    fields = validate_fields(body["fields"])
                    ids = [i for i in body["ids"] if i in library]
                    if not ids or not fields:
                        raise ValueError("nothing to apply")
                    results = apply_edits([{"id": i, "set": fields} for i in ids])
                    batch = record_batch(body.get("label") or "Edit", results)
                    self.send_json({"batchId": batch["batchId"], **summarize(results)})
                elif self.path == "/api/undo":
                    target = next(b for b in read_history() if b["batchId"] == body["batchId"])
                    edits = {}
                    # Walk backwards so each field ends at its earliest recorded value.
                    for c in reversed(target["changes"]):
                        edits.setdefault(c["id"], {})[c["field"]] = c["old"]
                    results = apply_edits([{"id": i, "set": s} for i, s in edits.items()])
                    record_batch(f"Undo: {target['label']}", results, undoes=target["batchId"])
                    self.send_json(summarize(results))
                else:
                    self.send_json({"error": "not found"}, 404)
        except (ValueError, KeyError, StopIteration, RuntimeError) as e:
            self.send_json({"error": str(e) or type(e).__name__}, 400)


def main():
    print("Loading library…")
    load_library()
    print(f"{len(library)} tracks. Open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
