import "dotenv/config";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Pool } from "pg";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const schema = readFileSync(path.join(__dirname, "../src/lib/schema.sql"), "utf8");
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  await pool.query(schema);
  console.log("Database schema is up to date.");
  await pool.end();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});