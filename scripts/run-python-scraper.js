/**
 * Run Python scraper with venv Python when available (Windows-friendly).
 * Does NOT open a browser here - browser opens when a job starts in Python.
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

console.log("[scraper] Python service starting (browser opens when you create a job)...");

// Guard: treat "0" or missing as disabled and force the safe default of 8.
// "0" is truthy in JS so the simple `|| "8"` fallback silently passes "0" through.
const _rawAttempts = process.env.PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS;
const _attempts = parseInt(_rawAttempts || "0", 10);

const env = {
  ...process.env,
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS: _attempts > 0 ? String(_attempts) : "8",
  ALLOW_OS_MOUSE_AUTOMATION: "false",
  FOCUS_BROWSER_ON_VERIFICATION: process.env.FOCUS_BROWSER_ON_VERIFICATION || "true",
};

const child = spawn(python, [main, ...args], {
  cwd: root,
  stdio: "inherit",
  env,
});

child.on("exit", (code) => process.exit(code ?? 1));

