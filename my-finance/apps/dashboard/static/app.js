const $ = id => document.getElementById(id);
let activeTab = 'positions', busy = false;
const money = value => typeof value === 'number' ? new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value) : '—';
const percent = value => typeof value === 'number' ? value.toFixed(2)+'%' : '—';
function headers() { return {'Content-Type':'application/json','X-API-Key':$('key').value,'X-Operator':$('operator').value.trim()}; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:headers(),body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
function reason() { const text = $('reason').value.trim(); if(text.length<10) throw new Error('Enter a decision reason of at least 10 characters.'); return text; }
function text(value) { return value === null || value === undefined ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value); }
function table(rows, columns, actions) {
  const parent = $('table'); parent.replaceChildren();
  if(!rows.length){parent.textContent='No records yet.';return;}
  const node=document.createElement('table'), head=document.createElement('tr');
  for(const [label] of columns){const th=document.createElement('th');th.scope='col';th.textContent=label;head.append(th);}
  if(actions){const th=document.createElement('th');th.textContent='Actions';head.append(th);}
  const thead=document.createElement('thead');thead.append(head);node.append(thead);
  const tbody=document.createElement('tbody');
  for(const row of rows){const tr=document.createElement('tr');for(const [,key,format] of columns){const td=document.createElement('td');td.textContent=format?format(row[key]):text(row[key]);tr.append(td);}if(actions){const td=document.createElement('td');actions(row,td);tr.append(td);}tbody.append(tr);}
  node.append(tbody);parent.append(node);
}
function action(parent,label,fn){const button=document.createElement('button');button.textContent=label;button.onclick=async()=>{button.disabled=true;try{await fn();$('status').textContent='Decision recorded';await loadTab();}catch(error){$('status').textContent=error.message;}finally{button.disabled=false;}};parent.append(button);}
function chart(points){const canvas=$('equity'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,1000,230);if(points.length<2){$('curve-summary').textContent='Equity history will appear after portfolio snapshots are recorded.';return;}
 const values=points.map(p=>p.equity_usd),lo=Math.min(...values),hi=Math.max(...values),range=hi-lo||1;
 ctx.strokeStyle='#2c3646';for(let y=20;y<=210;y+=47){ctx.beginPath();ctx.moveTo(65,y);ctx.lineTo(980,y);ctx.stroke();}
 ctx.strokeStyle='#8cdfb6';ctx.lineWidth=2;ctx.beginPath();values.forEach((v,i)=>{const x=65+i/(values.length-1)*915,y=210-(v-lo)/range*190;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
 ctx.fillStyle='#a0afc2';ctx.font='12px system-ui';ctx.fillText(money(hi),2,20);ctx.fillText(money(lo),2,210);$('curve-summary').textContent=`${points.length} snapshots. ${money(values[0])} → ${money(values.at(-1))}.`;}
async function loadTab(){const mode=encodeURIComponent($('mode').value);$('table-title').textContent=activeTab==='reviews'?'AI reviews':activeTab[0].toUpperCase()+activeTab.slice(1);
 switch(activeTab){
 case 'positions':{const d=await api('/portfolio/positions?mode='+mode);table(d.positions,[['Symbol','symbol'],['Quantity','quantity'],['Entry','entry_price',money],['Current','current_price',money],['Stop','stop_loss',money],['Target','take_profit',money]]);break;}
 case 'signals':{const d=await api('/signals');table(d.signals,[['Market','symbol'],['Strategy','strategy'],['Direction','action'],['Entry','entry',money],['Stop','stop_loss',money],['Time','created_at']],(row,td)=>action(td,'Review',()=>api('/agents/analyse',{signal_id:row.id})));break;}
 case 'strategies':{const d=await api('/strategies');table(d.strategies,[['Strategy','strategy'],['Status','status'],['Qualified','qualified'],['Blocking reason','blocking_reason']],(row,td)=>{
 action(td,'Evidence',async()=>{const d=await api('/strategies/'+encodeURIComponent(row.strategy)+'/evaluation');$('backtest-result').textContent=JSON.stringify(d,null,2);});
 action(td,'Admit paper',()=>api('/strategies/'+encodeURIComponent(row.strategy)+'/paper-testing',{reason:reason()}));
 action(td,row.qualified?'Revoke':'Qualify',()=>api('/strategies/'+encodeURIComponent(row.strategy)+'/qualification',{qualified:!row.qualified,reason:reason()}));});break;}
 case 'trades':{const d=await api('/trades?mode='+mode);table(d.trades,[['Symbol','symbol'],['Strategy','strategy'],['Entry','entry_price',money],['Exit','exit_price',money],['Net P&L','pnl_usd',money],['Reason','exit_reason']]);break;}
 case 'reviews':{const d=await api('/agents/reviews');table(d.reviews,[['Time','created_at'],['Summary','summary'],['Blocked','blocked']],(row,td)=>{const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='View reasoning';pre.textContent=JSON.stringify(row.analysis,null,2);details.append(summary,pre);td.append(details);});break;}
 case 'risk':{const d=await api('/risk/failed-checks');table(d.failed_checks,[['Rule','rule'],['Symbol','symbol'],['Reason','message'],['Observed','observed'],['Limit','limit'],['Time','created_at']]);break;}
 case 'approvals':{const d=await api('/control/approvals');table(d.approvals,[['ID','id'],['Proposed order','request'],['Order fingerprint','fingerprint'],['State','status'],['Note','note'],['Expires','expires_at']],(row,td)=>{if(row.status==='pending'){action(td,'Approve',()=>api('/control/approvals/'+row.id,{approved:true,reason:reason()}));action(td,'Reject',()=>api('/control/approvals/'+row.id,{approved:false,reason:reason()}));}});break;}
 }}
async function refresh(){if(busy)return;busy=true;$('refresh').disabled=true;try{const mode=encodeURIComponent($('mode').value);const results=await Promise.allSettled([api('/portfolio?mode='+mode),api('/portfolio/equity-curve?mode='+mode),api('/control/kill-switch'),api('/health/live')]);
 const errors=[];results.forEach(result=>{if(result.status==='rejected')errors.push(result.reason.message);});
 if(results[0].status==='fulfilled'){const p=results[0].value, stats=$('stats');stats.replaceChildren();for(const [label,value] of [['Equity',money(p.equity_usd)],['Cash',money(p.cash_usd)],['Exposure',percent(p.exposure_pct)],['Drawdown',percent(p.current_drawdown_pct)]]){const node=document.createElement('div');node.className='stat';const span=document.createElement('span'),strong=document.createElement('strong');span.textContent=label;strong.textContent=value;node.append(span,strong);stats.append(node);}}
 if(results[1].status==='fulfilled')chart(results[1].value.points);
 if(results[2].status==='fulfilled')$('breaker').textContent=results[2].value.engaged?'Trading halted: '+results[2].value.reason:'Trading halt released';
 $('connection').textContent=results[3].status==='fulfilled'?'API online':'API unavailable';await loadTab();$('status').textContent=errors.length?errors.join(' · '):'Updated '+new Date().toLocaleTimeString();
 }catch(error){$('status').textContent=error.message;}finally{busy=false;$('refresh').disabled=false;}}
$('refresh').onclick=refresh;$('mode').onchange=refresh;$('tabs').onclick=event=>{const tab=event.target.dataset.tab;if(tab){activeTab=tab;for(const button of $('tabs').children)button.classList.toggle('active',button.dataset.tab===tab);loadTab().catch(error=>{$('status').textContent=error.message;});}};
$('backtest').onsubmit=async event=>{event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;$('backtest-result').textContent='Backtest running…';try{const result=await api('/backtest',{strategy:$('strategy').value,symbol:$('symbol').value.trim(),source:$('source').value,bars:Number($('bars').value),evaluation:$('evaluation').checked});$('backtest-result').textContent=JSON.stringify(result,null,2);}catch(error){$('backtest-result').textContent=error.message;}finally{button.disabled=false;}};
for(const [id,engaged] of [['halt',true],['release',false]]){$(id).onclick=async()=>{try{await api('/control/kill-switch',{engaged,reason:reason()});await refresh();}catch(error){$('status').textContent=error.message;}};}
refresh();
