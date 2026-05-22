/**
 * Run Python scraper with venv Python when available (Windows-friendly).
 * Does NOT open a browser here — browser opens when a job starts in Python.
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const args = process.argv.slice(2);

const venvPython =
  process.platform === "win32"
    ? path.join(root, "venv", "Scripts", "python.exe")
    : path.join(root, "venv", "bin", "python");

const python = fs.existsSync(venvPython) ? venvPython : "python";
const main = path.join(root, "python_scraper", "main.py");

console.log("[scraper] Python service starting (browser opens when you create a job)…");

const child = spawn(python, [main, ...args], {
  cwd: root,
  stdio: "inherit",
  env: process.env,
});

child.on("exit", (code) => process.exit(code ?? 1));
