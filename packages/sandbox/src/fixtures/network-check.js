const http = require("node:http");
const req = http.get("http://example.com", { timeout: 3000 }, (res) => {
  console.log(`REACHED:${res.statusCode}`);
  process.exit(0);
});
req.on("error", (error) => {
  console.log(`BLOCKED:${error.code ?? error.message}`);
  process.exit(0);
});
req.on("timeout", () => {
  console.log("BLOCKED:timeout");
  req.destroy();
  process.exit(0);
});
