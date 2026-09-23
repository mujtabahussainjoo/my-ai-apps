// myPA desktop stub — loads local web UI. Requires Node + Electron.
// Web + CLI work without this; this file is only for the Desktop target.
const { app, BrowserWindow } = require('electron');
function create() {
  const w = new BrowserWindow({ width: 1024, height: 720, title: 'myPA' });
  w.loadURL(process.env.MYPA_URL || 'http://127.0.0.1:3210');
}
app.whenReady().then(create);
