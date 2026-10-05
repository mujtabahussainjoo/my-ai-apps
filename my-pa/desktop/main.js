const {app, BrowserWindow, dialog, shell} = require('electron');
const {spawn} = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
let backend;
function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer(); server.on('error', reject);
    server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)); });
  });
}
async function start() {
  let url = process.env.MYPA_URL;
  if (!url) {
    const port = await freePort();
    const root = app.isPackaged ? path.join(process.resourcesPath, 'backend') : path.resolve(__dirname, '..');
    backend = spawn(process.env.MYPA_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-m', 'mypa', 'web', '--port', String(port)], {cwd: root, stdio: 'ignore'});
    let failure;
    backend.on('error', error => { failure = error; });
    backend.on('exit', code => { failure = new Error(`Python backend exited (${code})`); });
    url = `http://127.0.0.1:${port}`;
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (failure) throw failure;
      try { const response = await fetch(`${url}/api/health`); const health = await response.json(); if (response.ok && health.app === 'myPA') { ready = true; break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!ready) throw new Error('Backend did not start. Install Python 3.10+ and myPA dependencies.');
  }
  const window = new BrowserWindow({width: 1024, height: 720, title: 'myPA', webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true}});
  window.webContents.setWindowOpenHandler(({url: target}) => { if (/^https?:/.test(target)) shell.openExternal(target); return {action: 'deny'}; });
  window.webContents.on('will-navigate', (event, target) => { if (new URL(target).origin !== new URL(url).origin) event.preventDefault(); });
  await window.loadURL(url);
}
app.whenReady().then(start).catch(error => { dialog.showErrorBox('myPA startup failed', error.message); app.quit(); });
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => { if (backend) backend.kill(); });
