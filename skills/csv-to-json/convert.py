import csv
import io
import json
import sys


def main() -> None:
    try:
        with open("/scratch/input.txt", "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(json.dumps({"error": "no input provided"}))
        sys.exit(1)

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
