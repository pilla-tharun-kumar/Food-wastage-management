'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {fresh:'Fresh',expiring:'Expiring soon',expired:'Expired',out_of_stock:'Out of stock'};
const state = {page:'overview',status:'',search:'',category:'',barcode:'',number:1,secondaryNumber:1,categories:[],products:[],batches:[],summary:null};
let inventoryRequest = 0, secondaryRequest = 0, scanner = null, toastTimer;
// A compact rail on desktop; a keyboard-accessible navigation drawer on phones.
const mobileLayout = window.matchMedia('(max-width: 700px)');
let sidebarCollapsed = false;
try { sidebarCollapsed = localStorage.getItem('foodbridge.sidebar.collapsed') === 'true'; } catch (_) { /* Storage may be disabled. */ }
function renderSidebar() {
  const open = document.body.classList.contains('sidebar-open');
  document.body.classList.toggle('sidebar-collapsed', sidebarCollapsed);
  const expanded = mobileLayout.matches ? open : !sidebarCollapsed;
  const label = mobileLayout.matches ? 'Close navigation' : expanded ? 'Collapse sidebar' : 'Expand sidebar';
  $('#sidebar-toggle').setAttribute('aria-expanded', String(expanded));
  $('#sidebar-toggle').setAttribute('aria-label', label);
  $('#sidebar-toggle').title = label;
  $('#sidebar-toggle span').textContent = mobileLayout.matches ? '×' : expanded ? '‹' : '›';
  $('#mobile-menu').setAttribute('aria-expanded', String(open));
  $('#sidebar-backdrop').hidden = !open;
  $('#workspace-sidebar').inert = mobileLayout.matches && !open;
  $('.main-shell').inert = mobileLayout.matches && open;
  $('.global-header').inert = mobileLayout.matches && open;
}
function closeNavigation(restoreFocus = true) {
  document.body.classList.remove('sidebar-open');
  renderSidebar();
  if (restoreFocus && mobileLayout.matches) $('#mobile-menu').focus();
}
$('#sidebar-toggle').onclick = () => {
  if (mobileLayout.matches) { closeNavigation(); return; }
  sidebarCollapsed = !sidebarCollapsed;
  try { localStorage.setItem('foodbridge.sidebar.collapsed', String(sidebarCollapsed)); } catch (_) {}
  renderSidebar();
};
$('#mobile-menu').onclick = () => {
  document.body.classList.add('sidebar-open');
  renderSidebar();
  $('#sidebar-toggle').focus();
};
$('#sidebar-backdrop').onclick = () => closeNavigation();
mobileLayout.addEventListener('change', () => closeNavigation(false));
document.addEventListener('keydown', event => {
  if (!mobileLayout.matches || !document.body.classList.contains('sidebar-open')) return;
  if (event.key === 'Escape') { event.preventDefault(); closeNavigation(); }
  if (event.key === 'Tab') {
    const controls = $$('button, a[href]', $('#workspace-sidebar')).filter(el => !el.disabled && el.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
renderSidebar();
function updateStatusTabs() {
  $$('[data-status]').forEach(button => {
    const selected = button.dataset.status === state.status;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
}
function csrf() { return document.cookie.split('; ').find(x => x.startsWith('csrftoken='))?.split('=').slice(1).join('=') || ''; }
function errorText(value) {
  if (Array.isArray(value)) return value.map(errorText).join('\n');
  if (value && typeof value === 'object') return Object.entries(value).map(([key,val]) => `${key === 'detail' ? '' : `${key}: `}${errorText(val)}`).join('\n');
  return String(value);
}
async function api(url, options = {}) {
  const headers = {'X-CSRFToken':csrf(),...options.headers};
  if (options.body && !(options.body instanceof FormData)) { headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body); }
  const response = await fetch(url, {...options, headers, credentials:'same-origin'});
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({detail:'The server could not complete the request. Please try again.'}));
  if (!response.ok) throw new Error(response.status === 401 ? 'Your session has ended. Reload the page and sign in again.' : errorText(data));
  return data;
}
async function allPages(url) {
  let results=[];
  while (url) { const data=await api(url); if (Array.isArray(data)) return data; results.push(...data.results); url=data.next; }
  return results;
}
function date(value) { return new Date(`${value}T00:00:00`).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}); }
function amount(value) { return Number(value).toLocaleString('en-IN',{maximumFractionDigits:3}); }
function badge(status) { return `<span class="badge ${esc(status)}">${esc(labels[status] || status)}</span>`; }
function toast(message) { clearTimeout(toastTimer); $('#toast').textContent=message; $('#toast').hidden=false; toastTimer=setTimeout(() => $('#toast').hidden=true,5000); }
function showError(error) { $('#global-error').textContent=error.message; $('#global-error').hidden=false; }
function safe(action) { return async (...args) => { try { await action(...args); } catch(error) { showError(error); } }; }
function modal(id) { const dialog=$(id); const error=$('.form-error',dialog); if(error) error.hidden=true; dialog.showModal(); return dialog; }
function setOptions(select, rows, label, empty='Choose a product') { select.innerHTML=`<option value="">${esc(empty)}</option>`+rows.map(row=>`<option value="${row.id}">${esc(label(row))}</option>`).join(''); }
async function loadProducts(selected) {
  state.products=await allPages('/api/products/');
  setOptions($('#batch-product'),state.products,p=>`${p.name} · ${p.sku} (${p.unit})`);
  if(selected) $('#batch-product').value=selected;
  updateUnit();
}
function updateUnit() { const product=state.products.find(p=>p.id===Number($('#batch-product').value)); $('#quantity-unit').textContent=product ? `(${product.unit})` : ''; }
async function loadSummary() {
  state.summary=await api('/api/summary/');
  const data=state.summary;
  $('#today').textContent=new Date(`${data.today}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'});
  $('#stat-total').textContent=data.total_batches;
  $('#stat-products').textContent=`Across ${data.products} product${data.products===1?'':'s'}`;
  for(const status of ['fresh','expiring','expired']) $(`#stat-${status}`).textContent=data.counts[status];
  $('#alert-badge').textContent=data.unread_alerts;
  const attention=data.counts.expiring+data.counts.expired;
  $('#attention-banner').hidden=!attention || state.page!=='overview';
  $('#attention-title').textContent=`${attention} batch${attention===1?' needs':'es need'} your attention`;
  $('#health-bar').innerHTML=Object.entries(data.counts).filter(([,count])=>count).map(([key,count])=>`<span class="health-segment ${key}" style="width:${count/Math.max(1,data.total_batches)*100}%" title="${esc(labels[key])}: ${count}"></span>`).join('');
  const colors={fresh:'#38cbb2',expiring:'#f4ad63',expired:'#f08780',out_of_stock:'#788da2'};
  $('#health-legend').innerHTML=Object.entries(data.counts).map(([key,count])=>`<span><i style="background:${colors[key]}"></i>${esc(labels[key])} <strong>${count}</strong></span>`).join('');
  let angle = 0;
  const slices = Object.entries(data.counts).filter(([,count]) => count).map(([key,count]) => {
    const start = angle; angle += count / Math.max(1,data.total_batches) * 100;
    return `${colors[key]} ${start}% ${angle}%`;
  });
  $('#health-ring').style.background = slices.length ? `conic-gradient(${slices.join(',')})` : '#edf1e6';
  $('#health-ring').setAttribute('aria-label', Object.entries(data.counts).map(([key,count]) => `${labels[key]}: ${count}`).join(', '));
  $('#health-percent').textContent = data.total_batches ? `${Math.round(data.counts.fresh/data.total_batches*100)}%` : '0%';
  const maxProducts = Math.max(1,...data.categories.map(c=>c.products));
  $('#category-chart').innerHTML = data.categories.length ? data.categories.map(c => `<div class="chart-category"><div class="chart-row"><span>${esc(c.category__name)}</span><strong>${c.products}</strong></div><div class="chart-track"><div class="chart-fill" style="width:${c.products/maxProducts*100}%"></div></div></div>`).join('') : '<p class="muted">Add products to see your category mix.</p>';
}
function inventoryRow(batch) {
  let expiryLabel=batch.days_to_expiry<0 ? `${Math.abs(batch.days_to_expiry)} day${batch.days_to_expiry===-1?'':'s'} ago` : batch.days_to_expiry===0 ? 'Expires today' : `${batch.days_to_expiry} day${batch.days_to_expiry===1?'':'s'} remaining`;
  const category=state.categories.find(c=>c.id===batch.category_id)?.code || '';
  return `<tr><td><div class="product-cell"><span class="product-symbol ${esc(category)}" aria-hidden="true">${esc(batch.product_name.slice(0,2).toUpperCase())}</span><div><strong>${esc(batch.product_name)}</strong><small>${esc(batch.sku)} · ${esc(batch.batch_number)}</small></div></div></td><td>${esc(batch.category_name)}</td><td><strong>${amount(batch.quantity)} <span class="muted">${esc(batch.unit)}</span></strong></td><td><span>${date(batch.expiry_date)}</span><small class="${batch.status==='expired'?'expiry-expired':batch.status==='expiring'?'expiry-warning':''}">${expiryLabel}</small></td><td>${badge(batch.status)}</td><td>${esc(batch.storage_location || '—')}</td><td><div class="row-actions"><button class="icon-button" data-edit="${batch.id}" title="Edit batch" aria-label="Edit ${esc(batch.product_name)}"><svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 4 5 5M3 21l5-1L21 7a2 2 0 0 0-5-5L4 15z"/></svg></button><button class="icon-button" data-adjust="${batch.id}" title="Adjust stock" aria-label="Adjust ${esc(batch.product_name)} stock"><svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/></svg></button><button class="icon-button" data-delete="${batch.id}" title="Delete batch" aria-label="Delete ${esc(batch.product_name)} batch"><svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button></div></td></tr>`;
}
async function loadInventory() {
  const requestId=++inventoryRequest;
  const params=new URLSearchParams({page:state.number});
  for(const key of ['status','search','category','barcode']) if(state[key]) params.set(key,state[key]);
  const data=await api(`/api/inventory/?${params}`);
  if(requestId!==inventoryRequest) return;
  state.batches=data.results;
  $('#inventory-count').textContent=`${data.count} batch${data.count===1?'':'es'}`;
  $('#inventory-body').innerHTML=data.results.length ? data.results.map(inventoryRow).join('') : '<tr><td colspan="7" class="empty-cell"><strong>No inventory matches yet.</strong><p>Add your first batch, import a CSV, or change the filters to see more inventory.</p></td></tr>';
  $('#page-info').textContent=data.count ? `Showing ${(state.number-1)*25+1}–${(state.number-1)*25+data.results.length} of ${data.count} batches` : '0 batches';
  $('#page-number').textContent=state.number;
  $('#previous-page').disabled=!data.previous; $('#next-page').disabled=!data.next;
  $('#scan-filter').hidden=!state.barcode;
  $('#scan-filter-text').textContent=`Barcode / QR filter: ${state.barcode}`;
}
const pageDetails={overview:['Inventory overview','Monitor your stock, prioritise expiring batches and reduce food waste.'],inventory:['Inventory management','Manage every product and batch, from arrival to its last fresh day.'],alerts:['Expiry alerts','Review the batches that need action before your next service.'],predictions:['Smart intelligence','Forecast demand, spot likely surplus and plan purchases within storage limits.'],categories:['Food categories','Food categories, perishability and storage guidance for your inventory.'],donations:['Donation records','Completed handovers, recipient records and quantities taken from stock.'],activity:['Activity history','Follow the stock trail with quantities, reasons and timestamps.']};
async function navigate(page) {
  state.page=page; state.secondaryNumber=1;
  if (mobileLayout.matches && document.body.classList.contains('sidebar-open')) closeNavigation();
  const [title,subtitle]=pageDetails[page];
  $('#page-title').textContent=title; $('#page-subtitle').textContent=subtitle;
  $('#page-eyebrow').textContent=page==='predictions'?'DEMAND FORECAST & WASTE RISK':'INVENTORY & EXPIRY TRACKING';
  $('.heading-actions').hidden=page==='predictions';
  const navigationTitle = $(`.nav-item[data-page="${page}"]`).getAttribute('aria-label');
  $('#breadcrumb-page').textContent=navigationTitle;
  document.title=`${navigationTitle} · FoodBridge`;
  $$('.nav-item[data-page]').forEach(button=>{button.classList.toggle('active',button.dataset.page===page);button.setAttribute('aria-current',button.dataset.page===page?'page':'false');});
  const inventory=['overview','inventory'].includes(page);
  $('#inventory-section').hidden=!inventory;
  $('#overview-stats').hidden=page!=='overview'; $('#overview-bottom').hidden=page!=='overview';
  $('#attention-banner').hidden=page!=='overview' || !state.summary || !(state.summary.counts.expiring+state.summary.counts.expired);
  $('#secondary-section').hidden=inventory;
  if(inventory) await loadInventory(); else await loadSecondary();
}
function emptyBlock(title,description) { return `<div class="empty-cell"><strong>${esc(title)}</strong><p>${esc(description)}</p></div>`; }
function forecastBars(points) {
  const values=points.map(point=>Number(point.quantity));
  const max=Math.max(1,...values);
  return `<div class="forecast-bars" role="img" aria-label="Seven-day demand forecast">${values.map((value,index)=>`<span style="height:${Math.max(9,Math.round(value/max*100))}%" title="Day ${index+1}: ${amount(value)}"></span>`).join('')}</div>`;
}
async function loadPredictions(requestId) {
  const [rows,categories,coverage]=await Promise.all([api('/api/predictions/'),api('/api/predictions/categories/'),api('/api/demand/coverage/')]);
  if(requestId!==secondaryRequest || state.page!=='predictions') return;
  state.predictions=rows;
  const demo=coverage.sources.find(source=>source.source==='demo')?.count || 0;
  const high=rows.filter(row=>row.risk_level==='high').length;
  const noPrediction=coverage.products.filter(product=>!rows.some(row=>row.product===product.product_id)).length;
  const stats=`<div class="prediction-stats"><article><span>PRODUCT FORECASTS</span><strong>${rows.length}</strong><small>Latest completed day</small></article><article><span>HIGH WASTE RISK</span><strong>${high}</strong><small>Prioritise these products</small></article><article><span>CATEGORY MODELS</span><strong>${categories.length}</strong><small>Grouped by category and unit</small></article><article><span>HISTORY RECORDS</span><strong>${coverage.records}</strong><small>${demo?`${demo} synthetic demo rows`:'Imported business data'}</small></article></div>`;
  const note=`<div class="prediction-note"><strong>${demo?'Demo history is synthetic.':'Forecasts use your imported history.'}</strong><span>${demo?'Replace demo rows with real sales, purchase and waste history before making purchasing decisions. ':''}A forecast is an estimate, not a guarantee. Risk uses stock, nearest expiry and projected demand. Reorder quantities require a storage capacity.</span></div>`;
  const table=rows.length?`<div class="table-scroll prediction-table" tabindex="0" role="region" aria-label="Product demand forecasts; scroll horizontally for all columns"><table><thead><tr><th>Product</th><th>Next 7 days</th><th>Stock</th><th>Nearest expiry</th><th>Waste risk</th><th>Expected surplus</th><th>Suggested reorder</th><th>Model</th><th>Planning</th></tr></thead><tbody>${rows.map(row=>`<tr><td><strong>${esc(row.product_name)}</strong><small>${esc(row.category)} · ${esc(row.sku)}</small></td><td><strong>${amount(row.forecast_7d)} ${esc(row.unit)}</strong>${forecastBars(row.daily_forecast)}</td><td>${amount(row.stock_quantity)} ${esc(row.unit)}</td><td>${row.nearest_expiry_date?date(row.nearest_expiry_date):'—'}</td><td><span class="risk-pill ${esc(row.risk_level)}">${row.risk_score}/100 · ${esc(row.risk_level)}</span></td><td>${amount(row.expected_surplus)} ${esc(row.unit)}</td><td>${row.reorder_quantity===null?'<span class="muted">Set capacity</span>':`${amount(row.reorder_quantity)} ${esc(row.unit)}`}</td><td><span class="model-chip">${esc(row.model_name)}</span><small>${row.history_days} days of history${row.backtest_mae===null?'':` · MAE ${amount(row.backtest_mae)}`}</small></td><td><button class="secondary compact" data-plan-product="${row.product}">Set capacity</button></td></tr>`).join('')}</tbody></table></div>`:emptyBlock('No current forecasts','Import at least 21 continuous completed days of history per SKU, then run predictions.');
  const categoryCards=categories.length?`<div class="category-forecast-grid">${categories.map(row=>`<article><span>${esc(row.category_name)} · ${esc(row.unit)}</span><strong>${amount(row.forecast_7d)}</strong><small>forecast demand next 7 days · ${esc(row.model_name)} model</small>${forecastBars(row.daily_forecast)}</article>`).join('')}</div>`:'<p class="muted prediction-empty">Category forecasts appear when each product in that category and unit has complete history.</p>';
  $('#secondary-content').innerHTML=`${stats}${note}<div class="prediction-subheading"><div><span class="section-kicker">PRODUCT DECISIONS</span><h3>Demand, risk and reorder</h3></div><span>${noPrediction} product${noPrediction===1?'':'s'} waiting for data</span></div>${table}<div class="prediction-subheading"><div><span class="section-kicker">CATEGORY OUTLOOK</span><h3>Next week by food category</h3></div></div>${categoryCards}`;
  $('#secondary-info').textContent=`${rows.length} current product forecasts · As of yesterday`;
  $('#secondary-prev').disabled=$('#secondary-next').disabled=true;$('#secondary-number').textContent='1';
}
async function loadSecondary() {
  const requestId=++secondaryRequest, page=state.page;
  const detail={alerts:['Batches to review','Acknowledging an alert keeps it visible until the stock is used, removed, or its expiry details change.'],predictions:['Demand forecast and waste risk','Use daily sales history to identify likely surplus. Configure each product’s capacity to receive reorder quantities.'],categories:['Know your food','Storage guidance is a general planning aid. Follow the product label and your business food-handling policy.'],donations:['Completed donations','Each recorded donation reduces stock and creates a transaction.'],activity:['Inventory transactions','Newest changes first. History is retained even after a batch is deleted.']}[page];
  if(!detail) return;
  $('#secondary-title').textContent=detail[0]; $('#secondary-description').textContent=detail[1]; $('#donate-button').hidden=page!=='donations';
  $('#prediction-import-button').hidden=$('#prediction-run-button').hidden=page!=='predictions';
  $('#prediction-model').hidden=page!=='predictions';
  if(page==='predictions') {await loadPredictions(requestId);return;}
  if(page==='categories') {
    $('#secondary-content').innerHTML=`<div class="category-grid">${state.categories.map(c=>`<article class="category-card"><h3>${esc(c.name)}</h3><code>${esc(c.code)}</code><span class="badge ${esc(c.perishability)}">${esc(c.perishability)} perishability</span><p><strong>${esc(c.storage)}</strong></p><p>${esc(c.guidance)}</p></article>`).join('')}</div>`;
    $('#secondary-info').textContent=`${state.categories.length} food categories`; $('#secondary-prev').disabled=$('#secondary-next').disabled=true; $('#secondary-number').textContent='1'; return;
  }
  const endpoint={alerts:'alerts',activity:'transactions',donations:'donations'}[page];
  const data=await api(`/api/${endpoint}/?page=${state.secondaryNumber}`);
  if(requestId!==secondaryRequest || state.page!==page) return;
  let html='';
  if(page==='alerts') html=data.results.length ? `<div class="alert-list">${data.results.map(a=>`<article class="alert-card"><div class="alert-content">${badge(a.severity)}<h3>${esc(a.product_name)} · ${esc(a.batch_number)}</h3><p>${amount(a.quantity)} ${esc(a.unit)} · Expiry ${date(a.expiry_date)} · ${a.days_to_expiry<0?`${-a.days_to_expiry} days past expiry`:a.days_to_expiry===0?'Expires today':`${a.days_to_expiry} days left`}</p></div>${a.read_at?'<span class="acknowledged">✓ Acknowledged</span>':`<button class="secondary compact" data-acknowledge="${a.id}">Acknowledge</button>`}<button class="text-button" data-open-batch="${a.batch}">View batch →</button></article>`).join('')}</div>` : emptyBlock('No expiry alerts','Stock nearing or past expiry will appear here automatically.');
  if(page==='activity') html=data.results.length ? `<div class="table-scroll"><table><thead><tr><th>Product / batch</th><th>Action</th><th>Change</th><th>Remaining</th><th>Reason / reference</th><th>By / time</th></tr></thead><tbody>${data.results.map(t=>`<tr><td><strong>${esc(t.snapshot.product)}</strong><small>${esc(t.snapshot.batch_number)}</small></td><td>${esc(t.kind)}</td><td>${Number(t.delta)>0?'+':''}${amount(t.delta)} ${esc(t.snapshot.unit)}</td><td>${amount(t.quantity_after)} ${esc(t.snapshot.unit)}</td><td>${esc(t.note || '—')}<small>${esc(t.reference)}</small></td><td>${esc(t.actor_name)}<small>${esc(new Date(t.created_at).toLocaleString('en-IN'))}</small></td></tr>`).join('')}</tbody></table></div>` : emptyBlock('Your activity trail starts here','Stock changes will appear here as you add and update inventory.');
  if(page==='donations') html=data.results.length ? `<div class="table-scroll"><table><thead><tr><th>Product / batch</th><th>Recipient</th><th>Quantity</th><th>Notes</th><th>Recorded</th></tr></thead><tbody>${data.results.map(d=>`<tr><td><strong>${esc(d.snapshot.product)}</strong><small>${esc(d.snapshot.batch_number)}</small></td><td>${esc(d.recipient)}</td><td>${amount(d.quantity)} ${esc(d.snapshot.unit)}</td><td>${esc(d.notes || '—')}</td><td>${esc(new Date(d.created_at).toLocaleString('en-IN'))}</td></tr>`).join('')}</tbody></table></div>` : emptyBlock('Good food can go further','Log a completed donation to record the recipient and update stock.');
  $('#secondary-content').innerHTML=html;
  $('#secondary-info').textContent=`${data.count} record${data.count===1?'':'s'}`;
  $('#secondary-number').textContent=state.secondaryNumber;
  $('#secondary-prev').disabled=!data.previous; $('#secondary-next').disabled=!data.next;
}
async function refresh() {
  $('#global-error').hidden=true;
  await loadSummary();
  if(['overview','inventory'].includes(state.page)) {state.number=1;await loadInventory();}
  else {state.secondaryNumber=1;await loadSecondary();}
}
async function openBatch(id) {
  const form=$('#batch-form');form.reset();
  const batch=id ? await api(`/api/inventory/${id}/`) : null;
  await loadProducts(batch?.product);
  $('#batch-dialog-title').textContent=batch?'Edit inventory batch':'Add inventory';
  $('#batch-product').disabled=!!batch; $('#new-product-button').hidden=!!batch;
  form.elements.id.value=batch?.id || '';form.elements.version.value=batch?.version || '';
  form.elements.received_date.value=state.summary.today;
  if(batch) for(const key of ['batch_number','quantity','received_date','expiry_date','storage_location','alert_days','notes']) form.elements[key].value=batch[key] ?? '';
  modal('#batch-dialog');
}
function bindForm(id, action) {
  $(id).addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget, button=$('button[type="submit"], .dialog-actions .primary, .dialog-actions .danger',form) || $('button',form);
    const error=$('.form-error',form) || $('.form-error',form.closest('dialog'));
    error.hidden=true;button.disabled=true;
    try { await action(Object.fromEntries(new FormData(form)),form); }
    catch(err) {error.textContent=err.message;error.hidden=false;}
    finally {button.disabled=false;}
  });
}
async function stopScanner() {
  if(scanner) { const current=scanner;scanner=null;try {await current.clear();}catch(error){$('#scanner-message').textContent='Camera closed. Reopen the scanner if you need to retry.';} }
}
async function findBarcode(value) {
  const barcode=value.trim();
  if(!barcode) throw new Error('Enter a barcode or QR value.');
  const data=await api(`/api/products/?barcode=${encodeURIComponent(barcode)}`);
  if(!data.count) throw new Error('No product matches this code in your business. Add it as a product barcode first.');
  state.barcode=barcode;state.number=1;state.status='';state.search='';state.category='';
  $('#inventory-search').value='';$('#category-filter').value='';updateStatusTabs();
  $('#scan-dialog').close();await stopScanner();await navigate('inventory');toast(`Found ${data.results[0].name}. Choose a batch to edit or adjust.`);
}
document.addEventListener('click',safe(async event=>{
  const target=event.target.closest('button');if(!target) return;
  if(target.classList.contains('close-dialog')) {target.closest('dialog').close();return;}
  if(target.dataset.page) await navigate(target.dataset.page);
  if('status' in target.dataset) {state.status=target.dataset.status;state.number=1;updateStatusTabs();await loadInventory();}
  if(target.dataset.statusShortcut) {state.status=target.dataset.statusShortcut;state.number=1;updateStatusTabs();await navigate('inventory');}
  if(target.dataset.edit || target.dataset.openBatch) await openBatch(target.dataset.edit || target.dataset.openBatch);
  if(target.dataset.adjust) {const batch=await api(`/api/inventory/${target.dataset.adjust}/`);$('#adjust-form').reset();$('#adjust-form').elements.id.value=batch.id;$('#adjust-description').textContent=`${batch.product_name} · ${batch.batch_number} · Current stock: ${amount(batch.quantity)} ${batch.unit}`;modal('#adjust-dialog');}
  if(target.dataset.delete) {const batch=await api(`/api/inventory/${target.dataset.delete}/`);$('#delete-form').elements.id.value=batch.id;$('#delete-form').elements.version.value=batch.version;$('#delete-description').textContent=`${batch.product_name} · ${batch.batch_number} · ${amount(batch.quantity)} ${batch.unit}`;modal('#delete-dialog');}
  if(target.dataset.acknowledge) {target.disabled=true;try{await api(`/api/alerts/${target.dataset.acknowledge}/acknowledge/`,{method:'POST'});await refresh();toast('Alert acknowledged.');}finally{target.disabled=false;}}
  if(target.dataset.planProduct) {const product=await api(`/api/products/${target.dataset.planProduct}/`);$('#planning-form').reset();$('#planning-form').elements.product.value=product.id;$('#planning-title').textContent=`Plan ${product.name}`;$('#planning-description').textContent=`Capacity and lead time for ${product.unit} stock.`;$('#planning-capacity').value=product.storage_capacity??'';$('#planning-lead').value=product.reorder_lead_days;modal('#planning-dialog');}
}));
$('#add-button').onclick=safe(()=>openBatch());
$('#new-product-button').onclick=()=>{$('#product-form').reset();modal('#product-dialog');};
$('#batch-product').onchange=updateUnit;
$('#import-button').onclick=()=>{$('#import-form').reset();modal('#import-dialog');};
$('#prediction-import-button').onclick=()=>{$('#demand-import-form').reset();modal('#demand-import-dialog');};
$('#prediction-run-button').onclick=safe(async()=>{const button=$('#prediction-run-button'),model=$('#prediction-model');button.disabled=model.disabled=true;button.textContent='Calculating…';try{const result=await api('/api/predictions/run/',{method:'POST',body:{model:model.value}});await loadSecondary();toast(`${result.updated.length} product forecasts updated.${result.skipped.length?` ${result.skipped.length} skipped: ${result.skipped[0].reason}`:''}`);}finally{button.disabled=model.disabled=false;button.textContent='Run predictions';}});
$('#category-filter').onchange=safe(async event=>{state.category=event.target.value;state.number=1;await loadInventory();});
let searchTimer;
$('#inventory-search').oninput=event=>{clearTimeout(searchTimer);state.search=event.target.value;state.number=1;searchTimer=setTimeout(safe(loadInventory),250);};
$('#previous-page').onclick=safe(async()=>{state.number--;await loadInventory();});
$('#next-page').onclick=safe(async()=>{state.number++;await loadInventory();});
$('#secondary-prev').onclick=safe(async()=>{state.secondaryNumber--;await loadSecondary();});
$('#secondary-next').onclick=safe(async()=>{state.secondaryNumber++;await loadSecondary();});
$('#clear-scan').onclick=safe(async()=>{state.barcode='';state.number=1;await loadInventory();});
$('#settings-button').onclick=()=>{if(mobileLayout.matches)closeNavigation();if(!state.summary)return;$('#settings-days').value=state.summary.business.expiry_alert_days;modal('#settings-dialog');};
if($('#mobile-settings')) $('#mobile-settings').onclick=$('#settings-button').onclick;
$('#scan-button').onclick=async()=>{
  $('#barcode-form').reset();modal('#scan-dialog');
  if(typeof Html5QrcodeScanner==='undefined') {$('#scanner-message').textContent='Camera scanner could not load. Use your USB scanner or type the code below.';return;}
  try {scanner=new Html5QrcodeScanner('scanner',{fps:10,qrbox:{width:240,height:180},rememberLastUsedCamera:false},false);let handling=false;scanner.render(async text=>{if(handling)return;handling=true;try{await findBarcode(text);}catch(error){const box=$('.form-error',$('#scan-dialog'));box.textContent=error.message;box.hidden=false;setTimeout(()=>handling=false,2500);}},()=>{});}
  catch(error){$('#scanner-message').textContent='Camera scanner unavailable. Try an image upload, USB scanner, or type the code below.';}
};
$('#scan-dialog').addEventListener('close',stopScanner);
$('#donate-button').onclick=safe(async()=>{
  $('#donation-form').reset();const batches=await allPages('/api/inventory/');
  setOptions($('#donation-batch'),batches.filter(b=>b.status!=='expired' && Number(b.quantity)>0),b=>`${b.product_name} · ${b.batch_number} · ${amount(b.quantity)} ${b.unit}`,'Choose an available batch');modal('#donation-dialog');
});
bindForm('#batch-form',async(data)=>{
  const id=data.id;delete data.id;data.alert_days=data.alert_days===''?null:Number(data.alert_days);
  if(id) {data.version=Number(data.version);delete data.product;} else delete data.version;
  await api(id?`/api/inventory/${id}/`:'/api/inventory/',{method:id?'PATCH':'POST',body:data});
  $('#batch-dialog').close();await refresh();toast(id?'Inventory batch updated.':'Inventory batch added.');
});
bindForm('#product-form',async data=>{data.storage_capacity=data.storage_capacity===''?null:data.storage_capacity;data.reorder_lead_days=Number(data.reorder_lead_days);const product=await api('/api/products/',{method:'POST',body:data});await loadProducts(product.id);$('#product-dialog').close();toast('Product created. Complete the batch details to add stock.');});
bindForm('#import-form',async(_,form)=>{const data=await api('/api/inventory/import-csv/',{method:'POST',body:new FormData(form)});$('#import-dialog').close();await refresh();toast(`${data.imported} inventory batches imported.`);});
bindForm('#demand-import-form',async(_,form)=>{const body=new FormData(form);const replace=body.get('replace')==='true';body.delete('replace');const data=await api(`/api/demand/import-csv/?replace=${replace}`,{method:'POST',body});$('#demand-import-dialog').close();await loadSecondary();toast(`${data.imported} demand records imported${data.replaced?` (${data.replaced} replaced)`:''}. Run predictions to update scores.`);});
bindForm('#planning-form',async data=>{const product=data.product;delete data.product;data.storage_capacity=data.storage_capacity===''?null:data.storage_capacity;data.reorder_lead_days=Number(data.reorder_lead_days);await api(`/api/products/${product}/planning/`,{method:'PATCH',body:data});let forecastError=null;try{await api('/api/predictions/run/',{method:'POST',body:{product:Number(product)}});}catch(error){forecastError=error;}$('#planning-dialog').close();await loadSecondary();toast(forecastError?`Planning saved. Forecast pending: ${forecastError.message}`:'Planning settings and forecast updated.');});
bindForm('#adjust-form',async data=>{const id=data.id;delete data.id;await api(`/api/inventory/${id}/adjust/`,{method:'POST',body:data});$('#adjust-dialog').close();await refresh();toast('Stock adjusted and recorded in activity history.');});
bindForm('#delete-form',async data=>{await api(`/api/inventory/${data.id}/`,{method:'DELETE',body:{version:Number(data.version)}});$('#delete-dialog').close();await refresh();toast('Batch deleted. Its history has been retained.');});
bindForm('#donation-form',async data=>{await api('/api/donations/',{method:'POST',body:data});$('#donation-dialog').close();await refresh();toast('Donation recorded and stock updated.');});
bindForm('#settings-form',async data=>{await api('/api/business/',{method:'PATCH',body:{expiry_alert_days:Number(data.expiry_alert_days)}});$('#settings-dialog').close();await refresh();toast('Expiry alert window updated.');});
bindForm('#barcode-form',async data=>findBarcode(data.barcode));
safe(async()=>{
  state.categories=await api('/api/categories/');
  $('#category-filter').innerHTML='<option value="">All categories</option>'+state.categories.map(c=>`<option value="${esc(c.code)}">${esc(c.name)}</option>`).join('');
  setOptions($('#product-category'),state.categories,c=>`${c.name} · ${c.perishability} perishability`,'Choose a category');
  await loadSummary();await loadInventory();
  const requestedSection=new URLSearchParams(window.location.search).get('section');
  if(requestedSection && pageDetails[requestedSection] && requestedSection!=='overview') await navigate(requestedSection);
})();
// Refresh time-sensitive alerts while the dashboard is open; scheduler handles closed sessions.
setInterval(()=>{if(!document.hidden && !$('dialog[open]')) safe(async()=>{await loadSummary();if(state.page==='alerts')await loadSecondary();else if(['overview','inventory'].includes(state.page))await loadInventory();})();},60000);
