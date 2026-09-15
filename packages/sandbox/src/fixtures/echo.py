import json
import sys

input_path = "/scratch/input.txt"
input_text = ""
try:
    with open(input_path, "r", encoding="utf-8") as f:
        input_text = f.read()
except FileNotFoundError:
    pass

print(json.dumps({"args": sys.argv[1:], "inputText": input_text}))
