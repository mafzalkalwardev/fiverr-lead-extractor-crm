const { app, BrowserWindow } = require("electron");
const path = require("path");

const TITLE = "Fiverr Lead Extractor CRM - FT Solutions";
const PORT = process.env.PORT || 3000;

let mainWindow;

function createWindow() {
  const iconPath = path.join(__dirname, "..", "public", "icon.svg");
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
  mainWindow.loadURL(`http://localhost:${PORT}`);
  mainWindow.on("page-title-updated", (e) => {
    e.preventDefault();
    mainWindow.setTitle(TITLE);
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
