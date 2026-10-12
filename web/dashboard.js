'use strict';
const $ = selector => document.querySelector(selector);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cash = n => '฿' + Math.round(Number(n)||0).toLocaleString('th-TH');
const dateThai = x => x ? new Date(x).toLocaleDateString('th-TH',{day:'numeric',month:'short',year:'numeric'}) : '—';
let csrf = '', state = {totals:{},surveys:[],customers:[]}, activeTab='home', lastDetail=null, inviteLink='';
let toastTimer;
function toast(message) {const n=$('#toast');n.textContent=message;n.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>n.classList.remove('show'),3500)}
async function api(url,method='GET',body) {
  const config = {method,credentials:'same-origin',headers:{}};
  if(body !== undefined){config.headers['Content-Type']='application/json';config.body=JSON.stringify(body)}
  if(method !== 'GET')config.headers['X-CSRF-Token']=csrf;
  let response;
  try {response=await fetch(url,config)}catch(e){throw Error('เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ กรุณาตรวจสอบการเชื่อมต่อ')}
  let result;try{result=await response.json()}catch(e){throw Error('เซิร์ฟเวอร์ตอบกลับไม่ถูกต้อง')}
  if(!response.ok)throw Error(result.error||'เกิดข้อผิดพลาด');
  return result;
}
async function boot(){
  try {const session=await api('/api/session'); if(session.authenticated){csrf=session.csrf;$('#loginView').hidden=true;$('#appView').hidden=false;await refresh()}else{$('#loginView').hidden=false;$('#appView').hidden=true}}
  catch(e){$('#loginView').hidden=false;$('#loginError').hidden=false;$('#loginError').textContent=e.message}
}
async function refresh(){state=await api('/api/overview');const t=state.totals;
  $('#totalCustomers').textContent=t.customers.toLocaleString('th-TH');$('#totalCompleted').textContent=t.completed.toLocaleString('th-TH');$('#totalPending').textContent=t.pending.toLocaleString('th-TH');$('#totalGap').textContent=cash(t.gap);
  const pct=t.surveys?Math.round(t.completed/t.surveys*100):0;$('#completePercent').textContent=pct+'%';$('#completeBar').style.width=pct+'%';
  $('#progressDone').textContent=t.completed;$('#progressPending').textContent=t.pending;$('#progressRevoked').textContent=t.surveys-t.completed-t.pending;
  renderSurveys('#recentTable',state.surveys.slice(0,5));renderFilteredSurveys();renderFilteredCustomers();
}
function openTab(tab){activeTab=tab;for(const id of ['home','surveys','customers'])$('#'+id+'Panel').hidden=(tab!==id);
  document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('selected',n.dataset.tab===tab));
  const cfg={home:['ภาพรวมแบบสำรวจ','ติดตามการตอบแบบสำรวจและช่องว่างความคุ้มครองของลูกค้า'],surveys:['แบบสำรวจทั้งหมด','รายการที่รอการตอบและผลสำรวจที่ส่งกลับมาแล้ว'],customers:['ฐานข้อมูลลูกค้า','จัดการรายชื่อ สร้างแบบสำรวจ และดูประวัติการดำเนินงาน']}[tab];
  $('#pageTitle').textContent=cfg[0];$('#pageDesc').textContent=cfg[1];
}
function chip(status){return status==='completed'?'<span class="chip done">✓ ส่งแล้ว</span>':status==='pending'?'<span class="chip">◷ รอการตอบ</span>':'<span class="chip revoked">ยกเลิก</span>'}
function renderSurveys(where,list){let html;
  if(!list.length)html='<div class="empty"><strong>ยังไม่มีรายการแบบสำรวจ</strong>เริ่มโดยกด “สร้างแบบสำรวจ” เพื่อเพิ่มรายชื่อลูกค้า</div>';
  else html=`<div class="table-wrap"><table><thead><tr><th>ลูกค้า</th><th>รูปแบบ</th><th>สถานะ</th><th>วันที่สร้าง</th><th>คุ้มครองที่ยังขาด</th><th style="text-align:right">จัดการ</th></tr></thead><tbody>${list.map(s=>`<tr><td><div class="person">${esc(s.name)}</div><span class="subtext">${esc(s.phone||'ไม่ระบุเบอร์โทร')} · #${s.id}</span></td><td><span class="chip mode ${s.mode==='advisor'?'advisor':''}">${s.mode==='advisor'?'ที่ปรึกษากรอก':'ลูกค้ากรอกเอง'}</span></td><td>${chip(s.status)}</td><td>${esc(dateThai(s.created_at))}</td><td class="money ${s.status==='completed'?'gap':''}">${s.status==='completed'?cash(s.gap):'—'}</td><td><div class="actions">${s.status==='completed'?`<button class="text-btn" data-action="detail" data-id="${s.id}">ดูรายงาน →</button>`:s.status==='pending'?`<button class="text-btn" data-action="renew" data-id="${s.id}">สร้างลิงก์ใหม่</button><button class="text-btn danger" data-action="revoke" data-id="${s.id}">ยกเลิก</button>`:'—'}</div></td></tr>`).join('')}</tbody></table></div>`;
  $(where).innerHTML=html;
}
function renderFilteredSurveys(){const q=$('#searchSurveys').value.trim().toLowerCase(),status=$('#statusFilter').value;const list=state.surveys.filter(s=>(status==='all'||s.status===status) && [s.name,s.phone,String(s.id)].some(v=>String(v||'').toLowerCase().includes(q)));renderSurveys('#allSurveys',list)}
function renderFilteredCustomers(){const q=$('#searchCustomers').value.trim().toLowerCase(),list=state.customers.filter(c=>[c.name,c.phone].some(v=>String(v||'').toLowerCase().includes(q)));
  $('#allCustomers').innerHTML=list.length?`<div class="table-wrap"><table><thead><tr><th>ลูกค้า</th><th>บันทึก</th><th>แบบสำรวจ</th><th>เพิ่มเมื่อ</th><th style="text-align:right">จัดการ</th></tr></thead><tbody>${list.map(c=>`<tr><td><div class="person">${esc(c.name)}</div><span class="subtext">${esc(c.phone||'ไม่ระบุเบอร์โทร')}</span></td><td><span class="subtext">${esc(c.notes||'—')}</span></td><td>${c.survey_count} รายการ</td><td>${dateThai(c.created_at)}</td><td><div class="actions"><button class="text-btn" data-action="newFor" data-id="${c.id}">＋ สร้างแบบสำรวจ</button><button class="text-btn" data-action="edit" data-id="${c.id}">แก้ไข</button><button class="text-btn danger" data-action="delete" data-id="${c.id}">ลบ</button></div></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty"><strong>ยังไม่มีรายชื่อลูกค้า</strong>กดสร้างแบบสำรวจเพื่อเพิ่มข้อมูลลูกค้าใหม่</div>';
}
function openCustomer(mode='customer',customer=null){$('#customerForm').reset();$('#customerFormError').hidden=true;$('#editingId').value='';$('#customerDialogTitle').textContent='สร้างแบบสำรวจใหม่';$('#customerSaveBtn').textContent='บันทึกและสร้างลิงก์ →';$('#modeField').hidden=false;
  document.querySelector(`input[name="newMode"][value="${mode}"]`).checked=true;
  if(customer){$('#editingId').value=customer.id;$('#customerName').value=customer.name;$('#customerPhone').value=customer.phone;$('#customerNotes').value=customer.notes;$('#customerDialogTitle').textContent='แก้ไขข้อมูลลูกค้า';$('#modeField').hidden=true;$('#customerSaveBtn').textContent='บันทึกข้อมูล'}
  $('#customerDialog').showModal();
}
async function makeInvitation(customerId,mode){const response=await api('/api/invitations','POST',{customerId,mode});await refresh();showInvite(response.path);}
function showInvite(path){inviteLink=new URL(path,location.origin).href;$('#inviteUrl').value=inviteLink;$('#inviteDialog').showModal()}
async function copyLink(){try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(inviteLink)}else{$('#inviteUrl').select();if(!document.execCommand('copy'))throw Error('copy unavailable')}toast('คัดลอกลิงก์แล้ว')}catch(e){toast('คัดลอกอัตโนมัติไม่ได้ กรุณาเลือกและคัดลอกลิงก์ในช่อง')}}
function blobDownload(name,value){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),500)}
function info(k,v){return `<p><b>${esc(k)}:</b> ${esc(v || '—')}</p>`}
async function detail(id){const r=await api('/api/surveys/'+id);lastDetail=r;$('#detailTitle').textContent='ผลสำรวจ — '+r.name;
  const d=r.response;if(!d){$('#detailBody').innerHTML='<div class="empty">ไม่มีผลสำรวจสำหรับรายการนี้</div>'}else {
    const list=a=>Array.isArray(a)&&a.length?a.map(esc).join(' · '):'ไม่ได้เลือก';
    const risk=d.risk==='self'?'รับความเสี่ยงด้วยตนเอง':d.risk==='transfer'?'พิจารณาโอนความเสี่ยง':'ไม่ได้ระบุ';
    $('#detailBody').innerHTML=`<div class="detail-stats"><div class="detail-stat"><span>ต้องการ (A)</span><b>${cash(r.desired)}</b></div><div class="detail-stat"><span>มีอยู่ (B)</span><b>${cash(r.covered)}</b></div><div class="detail-stat highlight"><span>ยังขาด (C)</span><b>${cash(r.gap)}</b></div></div>
    <div class="detail-section"><h3>ข้อมูลและความยินยอม</h3><div class="detail-grid">${info('ชื่อในแบบสำรวจ',d.customer)}${info('ชื่อในฐานข้อมูล',r.name)}${info('อายุ',d.age?d.age+' ปี':'')}${info('โทรศัพท์',d.phone||r.phone)}${info('วันที่ส่ง',dateThai(r.completed_at))}${info('วันให้ความยินยอม',dateThai(r.consent_at))}</div></div>
    <div class="detail-section"><h3>1. ความกังวลเกี่ยวกับโรคร้ายแรง</h3>${info('ความกังวล',d.concern==='worried'?'กังวล':d.concern==='not-worried'?'ไม่กังวล':'ไม่ระบุ')}${info('โรคที่เลือก',list(d.diseases))}${d.otherDisease?info('อื่น ๆ',d.otherDisease):''}</div>
    <div class="detail-section"><h3>2. พฤติกรรมที่เลือก</h3>${info('รายการ',list(d.behaviors))}</div>
    <div class="detail-section"><h3>3. ค่าใช้จ่ายจำเป็น</h3><div class="detail-grid">${[['บ้าน/เดือน',d.housePayment],['หนี้บ้านคงเหลือ',d.houseBalance],['รถ/เดือน',d.carPayment],['หนี้รถคงเหลือ',d.carBalance],['ใช้จ่ายครัวเรือน/เดือน',d.household],['ศึกษา/เทอม',d.educationSemester],['เลี้ยงดูบุพการี/เดือน',d.parents],['เดินทาง/เดือน',d.travel],['อื่น ๆ/เดือน',d.others]].map(([label,n])=>info(label,cash(Number(n)||0))).join('')}</div>${info('ค่าใช้จ่ายรวม/เดือน',cash(r.monthly))}${info('ระยะเวลาสำรอง',d.reserveYears+' ปี')}</div>
    <div class="detail-section"><h3>4. ความคุ้มครอง</h3>${info('ทุนเจอจ่ายจบ',cash(d.ciOnce))}${info('ทุนจ่ายซ้ำ (ครั้งแรก)',cash(d.ciRepeat))}${info('ทุนชดเชย',cash(d.ciDailyFund))}${info('ชดเชยรายวัน',cash(d.ciDailyRate)+' / วัน')}<p class="detail-small">ค่าชดเชยรายวันและจำนวนจ่ายซ้ำในอนาคตไม่รวมในเงินก้อน B · หนี้คงเหลือไม่ถูกบวกเข้าความคุ้มครอง A อัตโนมัติ</p></div>
    <div class="detail-section"><h3>5. แนวทางดูแลความเสี่ยง</h3>${info('วิธีจัดการ',risk)}${info('ที่ปรึกษา',d.advisor)}${info('ติดต่อที่ปรึกษา',d.advisorPhone)}</div>
    <p class="detail-small">เอกสารเพื่อประเมินเบื้องต้น ไม่ถือเป็นคำแนะนำการลงทุน/ประกันแบบเฉพาะบุคคลหรือการรับประกันผลประโยชน์</p>`;
  }
  $('#detailDialog').showModal();
}
async function handleAction(action,id){try {
  const survey=state.surveys.find(x=>x.id===id),customer=state.customers.find(x=>x.id===id);
  if(action==='detail')return detail(id);
  if(action==='renew') {if(!confirm('ลิงก์เดิมจะใช้ไม่ได้ทันที ต้องการสร้างลิงก์ใหม่ใช่หรือไม่?'))return;const x=await api(`/api/surveys/${id}/renew`,'POST',{});showInvite(x.path);toast('สร้างลิงก์ใหม่แล้ว · ลิงก์เดิมถูกยกเลิก')}
  if(action==='revoke'){if(!confirm('ยกเลิกแบบสำรวจนี้? ลิงก์จะใช้ส่งคำตอบไม่ได้อีก'))return;await api(`/api/surveys/${id}`,'DELETE');await refresh();toast('ยกเลิกแบบสำรวจแล้ว')}
  if(action==='newFor'){const mode=confirm(`สร้างแบบสำรวจให้ ${customer.name}\n\nกด OK = ส่งลิงก์ให้ลูกค้ากรอกเอง\nกด Cancel = ที่ปรึกษากรอกให้`) ? 'customer' : 'advisor';await makeInvitation(id,mode)}
  if(action==='edit')openCustomer('customer',customer);
  if(action==='delete'){if(!confirm(`ลบข้อมูลของ ${customer.name} รวมทั้งแบบสำรวจและผลลัพธ์ทั้งหมดอย่างถาวรหรือไม่?\nการกระทำนี้ย้อนกลับไม่ได้`))return;await api('/api/customers/'+id,'DELETE');await refresh();toast('ลบข้อมูลลูกค้าและแบบสำรวจแล้ว')}
}catch(e){toast(e.message)}}

$('#loginForm').addEventListener('submit',async e=>{e.preventDefault();const btn=$('#loginForm button');btn.disabled=true;$('#loginError').hidden=true;try{await api('/api/login','POST',{username:$('#username').value,password:$('#password').value});$('#password').value='';await boot()}catch(err){$('#loginError').textContent=err.message;$('#loginError').hidden=false}finally{btn.disabled=false}});
$('#logoutBtn').addEventListener('click',async()=>{try{await api('/api/logout','POST',{});}catch(e){}csrf='';state={totals:{},customers:[],surveys:[]};$('#appView').hidden=true;$('#loginView').hidden=false});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>openTab(b.dataset.tab)));
$('#newCustomerBtn').addEventListener('click',()=>openCustomer());document.querySelectorAll('[data-new-mode]').forEach(b=>b.addEventListener('click',()=>openCustomer(b.dataset.newMode)));
$('#searchSurveys').addEventListener('input',renderFilteredSurveys);$('#statusFilter').addEventListener('change',renderFilteredSurveys);$('#searchCustomers').addEventListener('input',renderFilteredCustomers);
document.addEventListener('click',e=>{const c=e.target.closest('[data-close]');if(c)document.getElementById(c.dataset.close).close();const a=e.target.closest('[data-action]');if(a)handleAction(a.dataset.action,Number(a.dataset.id))});
$('#customerForm').addEventListener('submit',async e=>{e.preventDefault();const btn=$('#customerSaveBtn');btn.disabled=true;$('#customerFormError').hidden=true;
  try{const payload={name:$('#customerName').value,phone:$('#customerPhone').value,notes:$('#customerNotes').value};const editing=Number($('#editingId').value);
    if(editing){await api('/api/customers/'+editing,'PATCH',payload);$('#customerDialog').close();await refresh();toast('แก้ไขข้อมูลลูกค้าแล้ว')}
    else{const result=await api('/api/customers','POST',payload);$('#customerDialog').close();await makeInvitation(result.id,document.querySelector('input[name="newMode"]:checked').value);toast('สร้างข้อมูลลูกค้าและลิงก์แล้ว')}
  }catch(err){$('#customerFormError').textContent=err.message;$('#customerFormError').hidden=false;if(!$('#customerDialog').open)toast(err.message)}finally{btn.disabled=false}
});
$('#copyInvite').addEventListener('click',copyLink);$('#openInvite').addEventListener('click',()=>{if(inviteLink)window.open(inviteLink,'_blank','noopener,noreferrer')});
$('#exportResult').addEventListener('click',()=>{if(lastDetail){const safe=(lastDetail.name||'client').replace(/[\\/:*?"<>|]/g,'_').slice(0,50);blobDownload(`LivingBenefits-${safe}-${lastDetail.id}.json`,lastDetail);toast('ดาวน์โหลดรายงาน JSON แล้ว · เก็บรักษาให้ปลอดภัย')}});
$('#printResult').addEventListener('click',()=>window.print());
boot();
