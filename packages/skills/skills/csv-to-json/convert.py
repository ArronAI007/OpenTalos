import json
import sys

delimiter = sys.argv[1] if len(sys.argv) > 1 else ","
input_path = "/scratch/input.txt"  # must match @opentalos/sandbox's SANDBOX_INPUT_PATH exactly

try:
    with open(input_path, "r", encoding="utf-8") as f:
        raw = f.read()
except FileNotFoundError:
    print("No input file found — nothing to convert.", file=sys.stderr)
    sys.exit(1)

rows = [line.strip().split(delimiter) for line in raw.splitlines() if line.strip()]
if not rows:
    print("Input contained no rows.", file=sys.stderr)
    sys.exit(1)

header, *body = rows
records = [dict(zip(header, row)) for row in body]
print(json.dumps(records))
