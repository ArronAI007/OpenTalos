const inputPath = "/scratch/input.txt";
let inputText = "";
try {
  inputText = require("node:fs").readFileSync(inputPath, "utf-8");
} catch {
  // No input file provided for this invocation — that's fine, just echo args.
}
console.log(JSON.stringify({ args: process.argv.slice(2), inputText }));
