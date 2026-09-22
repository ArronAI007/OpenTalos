import csv
import io
import json
import sys


def main() -> None:
    # 输入契约：要转换的 CSV 内容从 stdin 读（由 run-script 接口的 input_text 字段喂进来）。
    content = sys.stdin.read()
    if not content.strip():
        print(json.dumps({"error": "no input provided"}))
        sys.exit(1)

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    main()
