/**
 * Run Python scraper with venv Python when available (Windows-friendly).
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const venvPython =
  process.platform === "win32"
    ? path.join(root, "venv", "Scripts", "python.exe")
    : path.join(root, "venv", "bin", "python");

const python = fs.existsSync(venvPython) ? venvPython : "python";
const main = path.join(root, "python_scraper", "main.py");
const args = process.argv.slice(2);

const child = spawn(python, [main, ...args], {
  cwd: root,
  stdio: "inherit",
  env: process.env,
});

child.on("exit", (code) => process.exit(code ?? 1));
