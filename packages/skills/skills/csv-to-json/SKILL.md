---
name: csv-to-json
description: Converts delimited text (CSV-like, tab-separated, or similar) into a JSON array of objects, one per row, keyed by the header row's column names. Use when the user provides raw delimited text and wants it as JSON.
---

# csv-to-json

Call `run_skill_script` with:
- `skillName`: `"csv-to-json"`
- `scriptRelativePath`: `"convert.py"`
- `args`: a single-element array containing the column delimiter the user's text uses (e.g. `[","]` for comma-separated, `["\t"]` for tab-separated)
- `input`: the user's raw text, verbatim

The script treats the first line as column headers and every subsequent line as a row, splitting
each on the given delimiter, and prints a JSON array of objects (one per row, keyed by header name)
to stdout — return that output to the user as-is.
