const status = document.getElementById('status');
const providerNames = ['opencode', 'openai', 'anthropic', 'local'];
const fields = {};
let ready = false;
function field(parent, text, type, value) {
  const label = document.createElement('label'); label.textContent = text;
  const input = document.createElement('input'); input.type = type;
  if (type === 'checkbox') input.checked = !!value; else input.value = value || '';
  label.appendChild(input); parent.appendChild(label); return input;
}
async function load() {
  ready = false;
  try {
    const config = await api('/api/config');
    document.getElementById('default_model').value = config.default_model;
    document.getElementById('workspace').value = config.agent.workspace;
    document.getElementById('shell_enabled').checked = config.agent.shell_enabled;
    document.getElementById('max_steps').value = config.agent.max_steps;
    api('/api/models').then(data => { document.getElementById('local-models').textContent = 'Installed local models: ' + data.models.map(m => m.name).join(', '); }).catch(error => { document.getElementById('local-models').textContent = error.message; });
    document.getElementById('theme').value = config.theme; applyTheme(config.theme);
    const parent = document.getElementById('providers'); parent.replaceChildren();
    for (const name of providerNames) {
      const provider = config.providers[name] || {};
      const group = document.createElement('fieldset');
      const legend = document.createElement('legend'); legend.textContent = name; group.appendChild(legend);
      fields[name] = {enabled: field(group, 'Enabled ', 'checkbox', provider.enabled)};
      if (name !== 'opencode') {
        fields[name].model = field(group, 'Model (used when selecting this provider)', 'text', provider.model);
        if (name === 'local') fields[name].base_url = field(group, 'Ollama URL', 'url', provider.base_url);
        else {
          fields[name].api_key = field(group, 'API key or environment reference', 'password', '');
          fields[name].api_key.placeholder = provider.key_configured ? 'Saved key configured' : provider.api_key || 'API key';
        }
      }
      parent.appendChild(group);
    }
    ready = true; status.textContent = 'Settings loaded';
  } catch (error) { status.textContent = error.message; }
}
document.getElementById('settings').onsubmit = async event => {
  event.preventDefault(); if (!ready) return;
  const button = document.getElementById('save'); button.disabled = true;
  try {
    const providers = {};
    for (const name of providerNames) {
      providers[name] = {};
      for (const [key, input] of Object.entries(fields[name])) {
        if (key === 'api_key' && !input.value.trim()) continue;
        providers[name][key] = key === 'enabled' ? input.checked : input.value.trim();
      }
    }
    let selected = document.getElementById('default_model').value.trim();
    // The selected model is the source of truth; provider model fields offer a quick selection.
    const result = await api('/api/config', {agent: {workspace: document.getElementById('workspace').value.trim(), shell_enabled: document.getElementById('shell_enabled').checked, max_steps: Number(document.getElementById('max_steps').value)}, default_model: selected, theme: document.getElementById('theme').value, providers});
    applyTheme(result.config.theme);
    for (const name of providerNames) if (fields[name].api_key) fields[name].api_key.value = '';
    status.textContent = 'Saved. Effective model: ' + result.config.default_model + '. Project settings override global settings.';
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
};
document.getElementById('providers').onchange = event => {
  for (const name of providerNames) {
    if (event.target === fields[name]?.model) document.getElementById('default_model').value = name + '/' + event.target.value.trim();
  }
};
document.getElementById('reload').onclick = load;
async function rules() {
  const data = await api('/api/rules');
  const parent = document.getElementById('rules'); parent.replaceChildren();
  data.permissions.forEach((rule, index) => {
    const row = document.createElement('div'); row.className = 'row';
    const label = document.createElement('span'); label.textContent = `${rule.action} | ${rule.resource} | ${rule.effect}`;
    const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Remove'; button.className = 'ghost';
    button.onclick = () => mutateRules({op: 'remove', index}); row.append(label, button); parent.appendChild(row);
  });
  if (!data.permissions.length) parent.textContent = 'No custom rules.';
}
async function mutateRules(body) {
  try { await api('/api/rules', body); await rules(); status.textContent = 'Rules saved'; }
  catch (error) { status.textContent = error.message; }
}
document.getElementById('rule-form').onsubmit = event => {
  event.preventDefault(); mutateRules({op: 'add', action: document.getElementById('r_action').value.trim(), resource: document.getElementById('r_resource').value.trim(), effect: document.getElementById('r_effect').value});
};
document.getElementById('r_clear').onclick = () => mutateRules({op: 'clear'});
load(); rules().catch(error => { status.textContent = error.message; });
