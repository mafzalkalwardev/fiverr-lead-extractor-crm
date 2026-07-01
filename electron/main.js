const { requireIndusLicense } = require("../lib/indus_license");
const { app, BrowserWindow, shell, dialog } = require("electron");
const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const TITLE = "Fiverr Lead Extractor CRM - FT Solutions";
const PORT = process.env.PORT || 3000;
const ROOT = path.join(__dirname, "..");

let mainWindow;
let childProcs = [];

function readEnvValue(key) {
  const envPath = path.join(ROOT, ".env");
  if (!fs.existsSync(envPath)) return null;
  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const index = line.indexOf("=");
    if (index <= 0) continue;
    if (line.slice(0, index).trim().toUpperCase() === key.toUpperCase()) {
      return line.slice(index + 1).trim();
    }
  }
  return null;
}

function startLocalMongo() {
  const script = path.join(ROOT, "scripts", "start-local-mongo.ps1");
  const ps = path.join(
    process.env.SystemRoot || "C:\\Windows",
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe"
  );
  const result = spawnSync(ps, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-RootDir", ROOT], {
    cwd: ROOT,
    stdio: "inherit",
    windowsHide: true,
  });

  if (result.status !== 0) {
    const message =
      "Local database could not start. Please run app as Administrator once or contact FT Solutions +92307-9670503.";
    dialog.showErrorBox("Fiverr Lead CRM", message);
    return false;
  }

  const uri = readEnvValue("MONGODB_URI");
  if (uri) process.env.MONGODB_URI = uri;
  return true;
}

function runNpmScript(script) {
  const isWin = process.platform === "win32";
  const cmd = isWin ? "npm.cmd" : "npm";
  const proc = spawn(cmd, ["run", script], {
    cwd: ROOT,
    shell: isWin,
    stdio: "inherit",
    env: { ...process.env, PORT: String(PORT) },
  });
  childProcs.push(proc);
  proc.on("error", (err) => console.error(`[electron] ${script}:`, err));
  return proc;
}

function createWindow() {
  const iconPath = path.join(ROOT, "public", "icon.svg");
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: TITLE,
    icon: iconPath,
    backgroundColor: "#0f172a",
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  mainWindow.loadURL(`http://localhost:${PORT}/`);
  mainWindow.on("page-title-updated", (e) => {
    e.preventDefault();
    mainWindow.setTitle(TITLE);
  });
}

app.whenReady().then(async () => {
  try {
    await requireIndusLicense(ROOT);
  } catch (err) {
    dialog.showErrorBox('INDUS License', err.message || String(err));
    app.quit();
    return;
  }

  if (!startLocalMongo()) {
    app.quit();
    return;
  }

  runNpmScript("dev");
  runNpmScript("scraper:py");

  const waitOn = require("wait-on");
  waitOn({ resources: [`http://localhost:${PORT}/api/system/status`], timeout: 120000 })
    .then(() => createWindow())
    .catch(() => {
      console.warn("[electron] Server slow to start - opening window anyway");
      createWindow();
    });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  childProcs.forEach((p) => {
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(p.pid), "/f", "/t"]);
      } else {
        p.kill("SIGTERM");
      }
    } catch (_) {}
  });
  if (process.platform !== "darwin") app.quit();
});

app.on("web-contents-created", (_, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
});
