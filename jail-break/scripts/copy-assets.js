const fs = require("fs");
const path = require("path");

const srcDir = path.join(__dirname, "..", "src", "renderer");
const outDir = path.join(__dirname, "..", "dist", "renderer");

fs.mkdirSync(outDir, { recursive: true });
for (const f of ["index.html", "styles.css"]) {
  fs.copyFileSync(path.join(srcDir, f), path.join(outDir, f));
}
console.log("Assets copied to dist/renderer");
