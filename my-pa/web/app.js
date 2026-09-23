const log=document.getElementById('log'),inp=document.getElementById('in');let hist=[];
function add(t,me){const d=document.createElement('div');d.className='msg'+(me?' me':'');d.textContent=t;log.appendChild(d);}
async function send(){const t=inp.value.trim();if(!t)return;inp.value='';hist.push({role:'user',content:t});add(t,true);
const r=await(await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:hist})})).json();
hist.push({role:'assistant',content:r.reply});add(r.reply+'\n— '+r.model,false);}
document.getElementById('send').onclick=send;inp.onkeydown=e=>{if(e.key==='Enter')send();};
