const fs = require("node:fs");

const delimiter = process.argv[2] ?? ",";
const inputPath = "/scratch/input.txt"; // must match @opentalos/sandbox's SANDBOX_INPUT_PATH exactly

let raw = "";
try {
  raw = fs.readFileSync(inputPath, "utf-8");
} catch {
  console.error("No input file found — nothing to format.");
  process.exit(1);
}

const rows = raw
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line.length > 0)
  .map((line) => line.split(delimiter).map((cell) => cell.trim()));

if (rows.length === 0) {
  console.error("Input contained no rows.");
  process.exit(1);
}

const [header, ...body] = rows;
const lines = [
  `| ${header.join(" | ")} |`,
  `| ${header.map(() => "---").join(" | ")} |`,
  ...body.map((row) => `| ${row.join(" | ")} |`),
];
console.log(lines.join("\n"));
