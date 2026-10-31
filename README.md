# Apple Music Annotator

Local web page for bulk-editing Apple Music track metadata (genre, BPM, key, rating, year, grouping),
including streaming tracks that aren't downloaded.

```
python3 server.py
```

Then open http://localhost:8737. macOS will ask once for permission to control Music.

- **Key** is stored at the start of each track's Comments (`B♭ minor (8m) :: …`); only that prefix is changed.
- Every edit is logged to `data/history.jsonl` with the previous values and can be undone from the page.
- The library is cached in `data/library.json`; use **Reload library** after editing in Music itself.
