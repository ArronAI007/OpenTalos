---
name: text-to-table
description: Reformats a block of freeform delimited text into a Markdown table. Use when the user provides raw delimited text (CSV-like, tab-separated, or similar) and wants it presented as a table.
---

# text-to-table

Call `run_skill_script` with:
- `skillName`: `"text-to-table"`
- `scriptRelativePath`: `"format.js"`
- `args`: a single-element array containing the column delimiter the user's text uses (e.g. `[","]` for comma-separated, `["\t"]` for tab-separated)
- `input`: the user's raw text, verbatim

The script treats each line as a table row and splits each row on the given delimiter into
columns. The first row becomes the table header. It prints a complete Markdown table (header row,
separator row, and body rows) to stdout — return that output to the user as-is.
