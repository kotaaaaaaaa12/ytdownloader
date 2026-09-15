const $ = (id) => document.getElementById(id);
const url = $('url'), load = $('load'), mode = $('mode'), quality = $('quality');
const container = $('container'), ios = $('ios'), download = $('download');
const media = $('media'), thumb = $('thumb'), title = $('title'), meta = $('meta');
const status = $('status'), statusText = $('statusText'), statusDetail = $('statusDetail');
const fileLink = $('fileLink'), error = $('error');
const qualityField = $('qualityField'), containerField = $('containerField'), iosField = $('iosField');
let info = null;

function showError(value='') { error.textContent=value; error.classList.toggle('hidden', !value); }
function fmtDuration(sec) { if(!sec) return ''; const m=Math.floor(sec/60), s=Math.floor(sec%60); return `${m}:${String(s).padStart(2,'0')}`; }
function fmtSize(bytes) { const u=['B','KB','MB','GB']; let n=bytes||0,i=0; while(n>=1024&&i<u.length-1){n/=1024;i++} return `${n.toFixed(i?1:0)} ${u[i]}`; }
function syncMode(){ const audio=mode.value==='audio'; qualityField.classList.toggle('hidden',audio); iosField.classList.toggle('hidden',audio); }
mode.addEventListener('change', syncMode); syncMode();

load.addEventListener('click', async()=>{
  showError(); fileLink.classList.add('hidden'); download.disabled=true; load.disabled=true; load.textContent='Loading…';
  try{
    const r=await fetch('/api/info',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({url:url.value.trim()})});
    const body=await r.json(); if(!r.ok) throw new Error(body.detail||'Failed to load media information');
    info=body; title.textContent=body.title||'Untitled'; meta.textContent=[body.uploader,fmtDuration(body.duration)].filter(Boolean).join(' • ');
    if(body.thumbnail){thumb.src=body.thumbnail;thumb.style.display='block'} else thumb.style.display='none';
    media.classList.remove('hidden'); quality.innerHTML='';
    for(const h of body.heights){ const o=document.createElement('option'); o.value=String(h); const fps=body.fps?.[String(h)]; o.textContent=`${h}p${fps?` / up to ${fps} FPS`:''}`; quality.append(o); }
    download.disabled=false;
  }catch(e){ showError(e.message); }
  finally{load.disabled=false;load.textContent='Load';}
});

download.addEventListener('click', async()=>{
  showError(); fileLink.classList.add('hidden'); download.disabled=true; status.classList.remove('hidden'); statusText.textContent='Starting…'; statusDetail.textContent='';
  try{
    const payload={url:url.value.trim(),mode:mode.value,height:mode.value==='audio'?null:Number(quality.value||0)||null,container:container.value,ios_compatible:ios.checked};
    const r=await fetch('/api/download',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)}); const body=await r.json(); if(!r.ok) throw new Error(body.detail||'Could not start');
    const id=body.job_id;
    while(true){
      await new Promise(res=>setTimeout(res,1500));
      const sr=await fetch(`/api/status/${id}`); const job=await sr.json(); if(!sr.ok) throw new Error(job.detail||'Job disappeared');
      statusText.textContent=job.progress||job.status; statusDetail.textContent=job.size?fmtSize(job.size):'';
      if(job.status==='error') throw new Error(job.error||'Download failed');
      if(job.status==='done'){
        statusText.textContent='Done'; statusDetail.textContent=[job.width&&job.height?`${job.width}×${job.height}`:'',job.codec||'',fmtSize(job.size)].filter(Boolean).join(' • ');
        fileLink.href=`/api/file/${id}`; fileLink.textContent=`Download ${job.filename}`; fileLink.classList.remove('hidden'); break;
      }
    }
  }catch(e){showError(e.message);status.classList.add('hidden');}
  finally{download.disabled=false;}
});
