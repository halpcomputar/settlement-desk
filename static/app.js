const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="desk-token"]').content;
const labels = {unreviewed:'Unreviewed',maybe:'Maybe relevant',claimed:'Claimed',not_applicable:'Not applicable'};
const titles = {all:'All settlements',maybe:'Your shortlist',claimed:'Claimed settlements',not_applicable:'Not applicable'};
let rows=[], metadata={}, selected=null, view='all', dirty=false, refreshing=false, discovery={}, apiConfigured=false;
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const date = iso => iso ? new Date(iso+'T00:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}) : 'Not specified';
const days = row => {if(!row.deadline_iso)return null;const now=new Date();return Math.round((new Date(row.deadline_iso+'T00:00:00')-new Date(now.getFullYear(),now.getMonth(),now.getDate()))/86400000)};
function toast(message){$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('toast').classList.remove('show'),4000)}
async function api(path, options={}){const result=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Desk-Token':token,...options.headers}});if(!result.ok){let message='Could not complete that action.';try{const body=await result.json();if(typeof body.detail==='string')message=body.detail}catch{}throw new Error(message)}return result.json()}
function filtered(){const term=$('search').value.toLowerCase().trim(), status=$('status-filter').value, proof=$('proof-filter').value, deadline=$('deadline-filter').value, category=$('category-filter').value, hidePast=$('hide-past-deadlines').checked;return rows.filter(row=>{const d=days(row);return(view==='all'||row.review_status===view)&&(!term||`${row.name} ${row.description}`.toLowerCase().includes(term))&&(!status||row.review_status===status)&&(!proof||(proof==='unknown'?!['Yes','No'].includes(row.proof_required):row.proof_required===proof))&&(!category||row.category===category)&&(!hidePast||d===null||d>=0)&&(!deadline||(deadline==='unknown'?d===null:deadline==='past'?d!==null&&d<0:d!==null&&d>=0&&d<=Number(deadline)))}).sort((a,b)=>$('sort').value==='name'?a.name.localeCompare(b.name):(a.deadline_iso||'9999').localeCompare(b.deadline_iso||'9999')||a.name.localeCompare(b.name))}
function renderOverview(){
  $('saved-stat').textContent=rows.length;$('review-stat').textContent=rows.filter(row=>row.review_status==='unreviewed').length;$('deadline-stat').textContent=rows.filter(row=>days(row)!==null&&days(row)>=0&&days(row)<=30&&row.review_status!=='not_applicable').length;
  for(const status of ['all','maybe','claimed'])$(status+'-count').textContent=status==='all'?rows.length:rows.filter(row=>row.review_status===status).length;
  $('coverage-label').textContent=metadata.sample_only?'Public sample snapshot':'Saved collection · partial coverage';
  $('sample-note').innerHTML=metadata.sample_only?'<span class="note-icon">i</span><span><strong>A small start.</strong> These are three public sample records, saved as a historical snapshot. Refresh to fetch up to 50 recent listings.</span>':'<span class="note-icon">i</span><span><strong>Your saved collection.</strong> Refresh checks up to 50 recent listings. Find more settlements checks additional pages. Your reviews and older records stay saved.</span>';
  $('last-sync').textContent=metadata.last_refresh?'Last fetched '+new Date(metadata.last_refresh).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):'No refresh yet';
}
function renderList(){const visible=filtered();$('result-count').textContent=visible.length;$('view-title').textContent=titles[view];$('settlement-list').innerHTML=visible.length?visible.map(row=>{const d=days(row);return `<button class="settlement-row ${selected===row.object_id?'selected':''}" data-id="${esc(row.object_id)}" aria-pressed="${selected===row.object_id}"><div><div class="row-title">${esc(row.name)}</div><p class="row-description">${esc(row.description||'Eligibility details not available in this listing.')}</p><div class="row-tags"><span class="tag ${row.review_status}">${labels[row.review_status]}</span><span class="proof-text">${row.proof_required==='No'?'No proof listed':row.proof_required==='Yes'?'Proof required':'Proof unclear'}</span></div></div><div class="row-date ${d!==null&&d>=0&&d<=30?'urgent':''}">${row.deadline_iso?esc(new Date(row.deadline_iso+'T00:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})):'Unknown'}<small>${d===null?'Check notice':d<0?'Past deadline':d===0?'Today':d+' days left'}</small></div></button>`}).join(''):'<div class="empty"><strong>No settlements in this view</strong>If your collection is empty, configure Parse in .env and use Refresh listings. Otherwise, try another filter.</div>';
document.querySelectorAll('.settlement-row').forEach(button=>button.addEventListener('click',()=>selectRow(button.dataset.id)));
}
function allowDiscard(){return !dirty||window.confirm('Discard the unsaved changes to this review?')}
function selectRow(id){if(selected===id)return;if(!allowDiscard())return;selected=id;dirty=false;renderList();renderDetail();$('detail').scrollTop=0;if(innerWidth<=700)$('detail').scrollIntoView({behavior:'smooth',block:'start'})}
function renderDetail(){const row=rows.find(item=>item.object_id===selected);if(!row){$('detail').innerHTML='<div class="empty detail-empty"><div class="empty-symbol">▤</div><strong>A closer look</strong>Select a settlement to review its eligibility and keep your notes.</div>';return}
  $('detail').innerHTML=`<div class="detail-top"><span>SETTLEMENT DETAILS</span><span>Source summary</span></div><div class="detail-body"><div class="category" title="Category inferred from the listing title">${esc(row.category)}</div><h2>${esc(row.name)}</h2><dl class="detail-facts"><div><dt>Listed payout</dt><dd>${esc(row.payout_amount||'Not specified')}</dd></div><div><dt>Claim deadline</dt><dd>${esc(row.deadline_iso?date(row.deadline_iso):row.claim_deadline||'Unknown')}</dd></div><div><dt>Proof required</dt><dd>${esc(row.proof_required||'Unclear')}</dd></div><div><dt>Your review</dt><dd>${labels[row.review_status]}</dd></div></dl><section class="detail-section"><h3>WHO MAY QUALIFY</h3><p>${esc(row.description||'Check the official notice for eligibility details.')}</p></section>${row.official_website?`<a class="button secondary official-link" href="${esc(row.official_website)}" target="_blank" rel="noopener noreferrer">Open official settlement site <span aria-hidden="true">↗</span></a>`:'<p class="fineprint">Official website not supplied by the source.</p>'}<p class="fineprint">Payout terms and eligibility are from the source and have not been independently verified. “No proof” does not remove eligibility requirements. Category is inferred from the title.</p><form class="review-form" id="review-form"><label for="review-status">MY REVIEW</label><select id="review-status">${Object.entries(labels).map(([value,label])=>`<option value="${value}" ${row.review_status===value?'selected':''}>${label}</option>`).join('')}</select><label for="review-notes">PRIVATE NOTES</label><textarea id="review-notes" maxlength="5000" placeholder="What should you check? Add dates, reminders, or a claim confirmation reference.">${esc(row.notes)}</textarea><div class="save-row"><span class="save-state" id="save-state">Saved on this computer</span><button class="button primary" type="submit" id="save-review">Save review</button></div></form></div>`;
  for(const id of ['review-status','review-notes'])$(id).addEventListener('input',()=>{dirty=true;$('save-state').textContent='Unsaved changes'});
  $('review-form').addEventListener('submit',async event=>{event.preventDefault();const id=selected, status=$('review-status').value, notes=$('review-notes').value;$('save-review').disabled=true;try{await api('/api/reviews/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify({status,notes})});row.review_status=status;row.notes=notes;dirty=false;renderOverview();renderList();renderDetail();toast('Review saved on this computer')}catch(error){toast(error.message);$('save-review').disabled=false}});
}
const discoveryMessages = {
  empty: 'No further listings were returned. Refresh listings to start another search.',
  repeated: 'Parse returned a page already checked. Search stopped to avoid repeated requests. Refresh listings to start another search.'
};
function updateFetchButtons(){
  $('refresh-open').disabled=!apiConfigured||refreshing;
  $('find-more-open').disabled=!apiConfigured||refreshing||!!discovery.stop_reason;
  $('find-more-open').title=discoveryMessages[discovery.stop_reason]||'Check the next page from Parse';
}
async function load(){
  const data=await api('/api/settlements');rows=data.settlements;metadata=data.metadata;
  discovery=data.discovery;apiConfigured=data.api_configured;
  if(!selected&&rows.length)selected=(rows.find(row=>row.name.includes('Amazon'))||rows[0]).object_id;
  updateFetchButtons();
  $('refresh-open').title=apiConfigured?'Fetch one page from Parse':'Set PARSE_API_KEY and PARSE_SCRAPER_ID in .env, then restart';
  $('discovery-status').textContent=discoveryMessages[discovery.stop_reason]||'';
  renderOverview();renderList();renderDetail();
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{view=button.dataset.view;$('status-filter').value='';document.querySelectorAll('[data-view]').forEach(item=>item.classList.toggle('active',item===button));renderList()}));
for(const id of ['search','status-filter','proof-filter','category-filter','sort'])$(id).addEventListener(id==='search'?'input':'change',renderList);
$('hide-past-deadlines').addEventListener('change',()=>{if($('hide-past-deadlines').checked&&$('deadline-filter').value==='past')$('deadline-filter').value='';renderList()});
$('deadline-filter').addEventListener('change',()=>{if($('deadline-filter').value==='past')$('hide-past-deadlines').checked=false;renderList()});
$('clear-filters').addEventListener('click',()=>{for(const id of ['search','status-filter','proof-filter','deadline-filter','category-filter'])$(id).value='';$('hide-past-deadlines').checked=false;renderList()});
for(const mode of ['refresh','find-more']){
  const dialog=$(mode+'-dialog'), confirm=$(mode+'-confirm');
  $(mode+'-open').addEventListener('click',()=>{
    if(refreshing||!allowDiscard())return;
    dirty=false;renderDetail();$(mode+'-error').textContent='';dialog.showModal();
  });
  $(mode+'-cancel').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('cancel',event=>{if(refreshing)event.preventDefault()});
  confirm.addEventListener('click',async()=>{
    if(refreshing)return;
    refreshing=true;updateFetchButtons();
    const label=confirm.textContent;
    dialog.querySelectorAll('button').forEach(button=>button.disabled=true);
    confirm.textContent='Fetching…';$(mode+'-error').textContent='';
    let result;
    try{
      result=await api('/api/'+mode,{method:'POST'});
    }catch(error){$(mode+'-error').textContent=error.message}
    if(result){
      dialog.close();
      try{
        await load();
        const message=mode==='find-more'
          ?`${result.added} new settlement${result.added===1?'':'s'} added; ${result.existing} already saved. ${discoveryMessages[result.stop_reason]||'You can search the next page whenever you’re ready.'}`
          :`${result.updated} listings checked`;
        if(mode==='find-more')$('discovery-status').textContent=message;
        toast(mode==='find-more'?`${result.added} new settlement${result.added===1?'':'s'} added`:message);
      }catch{
        // The paid request succeeded. Do not encourage another paid request to fix a local reload.
        $('discovery-status').textContent='The fetch completed, but the updated collection could not be loaded. Reload this page to see the saved results.';
      }
    }
    refreshing=false;updateFetchButtons();
    dialog.querySelectorAll('button').forEach(button=>button.disabled=false);
    confirm.textContent=label;
  });
}
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue=''}});
load().catch(error=>{$('settlement-list').innerHTML='<div class="empty"><strong>Could not load your collection</strong>Check that the local dashboard server is running, then reload.</div>';toast(error.message)});
