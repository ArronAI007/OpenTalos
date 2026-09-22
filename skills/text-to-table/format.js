const fs = require("node:fs");

function main() {
  // 输入契约：要转换的文本从 stdin 读（由 run-script 接口的 input_text 字段喂进来）。
  const content = fs.readFileSync(0, "utf-8");
  if (!content.trim()) {
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
