const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

const TITLE = "Fiverr Lead Extractor CRM - FT Solutions";
const PORT = process.env.PORT || 3000;
const ROOT = path.join(__dirname, "..");

let mainWindow;
let childProcs = [];

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
  mainWindow.loadURL(`http://localhost:${PORT}/login`);
  mainWindow.on("page-title-updated", (e) => {
    e.preventDefault();
    mainWindow.setTitle(TITLE);
  });
}

app.whenReady().then(() => {
  runNpmScript("dev");
  runNpmScript("scraper:py");

  const waitOn = require("wait-on");
  waitOn({ resources: [`http://localhost:${PORT}/api/system/status`], timeout: 120000 })
    .then(() => createWindow())
    .catch(() => {
      console.warn("[electron] Server slow to start — opening window anyway");
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
