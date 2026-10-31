// Reads every track in the Music library in one bulk pass per property.
// Returns columnar JSON: {prop: [value, ...], ...}, all arrays in the same order.
const PROPS = [
  "persistentID", "name", "artist", "albumArtist", "album", "genre", "bpm",
  "year", "rating", "ratingKind", "grouping", "comment", "trackNumber",
  "discNumber", "duration", "cloudStatus",
];

function run() {
  const tracks = Application("Music").libraryPlaylists[0].tracks;
  const cols = {};
  PROPS.forEach(p => { cols[p] = tracks[p](); });
  return JSON.stringify(cols);
}
