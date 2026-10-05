const log = document.getElementById('log');
const input = document.getElementById('in');
const sendButton = document.getElementById('send');
const status = document.getElementById('status');
let history = [], busy = false;
try { history = JSON.parse(localStorage.getItem('mypa-history') || '[]'); if (!Array.isArray(history)) history = []; } catch {}
for (const message of history) add(message.content, message.role === 'user');
function add(text, me) {
  const node = document.createElement('article'); node.className = 'msg' + (me ? ' me' : ' assistant');
  const label = document.createElement('div'); label.className = 'message-label'; label.textContent = me ? 'You · query' : 'myPA · model reply';
  const body = document.createElement('div'); body.className = 'message-body'; body.textContent = text;
  node.append(label, body); log.appendChild(node); node.scrollIntoView({block: 'nearest'}); return body;
}
function activity(event, before) {
  const detail = document.createElement('details');
  const title = document.createElement('summary'); title.textContent = (event.ok ? '✓ ' : '✗ ') + event.tool;
  const body = document.createElement('pre'); body.textContent = JSON.stringify(event.arguments, null, 2) + '\n' + event.result;
  detail.append(title, body); log.insertBefore(detail, before);
}
async function send() {
  const text = input.value.trim(); if (!text || busy) return;
  busy = true; sendButton.disabled = true;
  const messages = [...history, {role: 'user', content: text}];
  add(text, true); input.value = ''; const reply = add('', false);
  const started = Date.now(); let phase = 'Connecting to local model', completed = false;
  const updateStatus = () => { status.textContent = `${phase} · ${Math.floor((Date.now() - started) / 1000)}s`; };
  updateStatus(); const timer = setInterval(updateStatus, 1000);
  try {
    const response = await fetch('/api/agent/stream', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({messages, mode: document.getElementById('mode').value})});
    if (!response.ok) { const error = await response.json(); throw new Error(error.error || 'Request failed'); }
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
    function handle(line) {
      if (!line.trim()) return; const event = JSON.parse(line);
      if (event.type === 'error') throw new Error(event.error);
      if (event.type === 'status') phase = event.text;
      if (event.type === 'token') { reply.textContent += event.text; phase = 'Replying'; }
      if (event.type === 'reset') reply.textContent = '';
      if (event.type === 'tool') activity(event.event, reply.parentElement);
      if (event.type === 'done') {
        reply.textContent = event.reply; completed = true;
        history = [...messages, {role: 'assistant', content: event.reply}].slice(-100);
        try { localStorage.setItem('mypa-history', JSON.stringify(history)); } catch {}
        phase = `${event.model} · complete`;
      }
      updateStatus();
    }
    try {
      while (true) {
        const {value, done} = await reader.read(); buffer += decoder.decode(value, {stream: !done});
        let end; while ((end = buffer.indexOf('\n')) >= 0) { handle(buffer.slice(0, end)); buffer = buffer.slice(end + 1); }
        if (done) break;
      }
      if (buffer.trim()) handle(buffer);
      if (!completed) throw new Error('Connection ended before the answer completed');
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  } catch (error) {
    reply.parentElement.classList.add('failed');
    phase = error.message; updateStatus(); if (!input.value) input.value = text;
  } finally {
    clearInterval(timer); busy = false; sendButton.disabled = false; input.focus();
  }
}
sendButton.onclick = send;
input.onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } };
document.getElementById('clear').onclick = () => {
  if (busy) return;
  history = []; localStorage.removeItem('mypa-history'); log.replaceChildren(); status.textContent = 'New conversation';
};
api('/api/config').then(config => {
  applyTheme(config.theme); if (!busy) status.textContent = config.default_model;
}).catch(error => { if (!busy) status.textContent = error.message; });
