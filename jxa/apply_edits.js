// Applies edits to library tracks. argv[0] is a path to a JSON file containing
// [{id: persistentID, set: {field: value, ...}}, ...].
// Fields are Music track properties (genre, bpm, year, rating, grouping, comment)
// plus the virtual field "key", which rewrites the key prefix of the comment,
// e.g. "B♭ minor (8m) :: 2010s hip-hop" -> "A minor (1m) :: 2010s hip-hop".
// Returns [{id, ok, changes: [{field, old, new}], error?}, ...].
ObjC.import("Foundation");

const KEY_RE = /^[A-G][♭♯b#]?\s+(major|minor)\s+\(\d{1,2}[md]\)/;

function readFile(path) {
  return $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null).js;
}

function withKey(comment, keyLabel) {
  comment = comment || "";
  const m = KEY_RE.exec(comment);
  let rest = comment;
  if (m) rest = comment.slice(m[0].length).replace(/^ :: /, "").replace(/^\n/, "");
  if (!keyLabel) return rest;
  if (!rest) return keyLabel;
  return keyLabel + (rest.startsWith("last.fm:") ? "\n" : " :: ") + rest;
}

function readField(t, field) {
  // A computed (album-derived) rating isn't a real per-track value; treat it as unrated.
  if (field === "rating" && t.ratingKind() === "computed") return 0;
  return t[field]();
}

function run(argv) {
  const edits = JSON.parse(readFile(argv[0]));
  const tracks = Application("Music").libraryPlaylists[0].tracks;
  const results = [];
  for (const edit of edits) {
    const result = { id: edit.id, ok: true, changes: [] };
    try {
      const t = tracks.whose({ persistentID: edit.id })[0];
      for (let [field, value] of Object.entries(edit.set)) {
        if (field === "key") {
          field = "comment";
          value = withKey(t.comment(), value);
        }
        const old = readField(t, field);
        if (old === value) continue;
        t[field] = value;
        result.changes.push({ field, old, new: readField(t, field) });
      }
    } catch (err) {
      result.ok = false;
      result.error = String(err);
    }
    results.push(result);
  }
  return JSON.stringify(results);
}
