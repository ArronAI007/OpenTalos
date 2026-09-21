const fs = require("node:fs");

function main() {
  let content = "";
  try {
    content = fs.readFileSync("/scratch/input.txt", "utf-8");
  } catch {
    console.log("no input provided");
    return;
  }
  const delimiter = process.argv[2] || ",";
  const lines = content.trim().split("\n").filter((line) => line.length > 0);
  if (lines.length === 0) return;
  const rows = lines.map((line) => line.split(delimiter).map((cell) => cell.trim()));
  const header = rows[0];
  const separator = header.map(() => "---");
  const tableRows = [header, separator, ...rows.slice(1)];
  const markdown = tableRows.map((row) => `| ${row.join(" | ")} |`).join("\n");
  console.log(markdown);
}

main();
