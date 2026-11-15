import {datasets,sources} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {SyncStatus,SyncMode} from '../constants/enums.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

const writable=()=>session.user.role!=='viewer';
const chip=status=>'<span class="sync-chip '+(status||'')+'">'+esc(SyncStatus[status]||status||'—')+'</span>';

function positionLine(d){
 const total=d.source_head||0;
 const pos=d.source_position||0;
 const pct=total?Math.min(100,Math.round(pos/total*100)):0;
 return '<div class="position"><div class="position-track"><span style="width:'+pct+'%"></span></div><p><strong>源端位置 '+pos+' / '+total+'</strong><span>'+(d.lag>0?'落后 '+d.lag+' 个变更':'与源端一致')+'</span></p></div>';
}

function batchPanel(d,versions,verifyResult){
 verifyResult=verifyResult||(workspace.lastVerify&&workspace.lastVerify.dataset_id===d?.id?workspace.lastVerify:null);
 if(!d)return '<section class="panel"><div class="empty">选择左侧批次查看接入状态。</div></section>';
 const isSource=d.mode==='source';
 return '<section class="panel sync-panel"><div class="section-title"><h2>'+esc(d.name)+'</h2>'+chip(d.sync_status)+'</div>'+
  '<div class="sync-facts"><div><span>已发布版本</span><strong>'+(d.current_version?'v'+d.current_version:'无')+'</strong><small>'+(d.current_version_superseded?'已被新版本替换':'当前分析依据')+'</small></div>'+
  '<div><span>进行中批次</span><strong>'+(d.active_version?'v'+d.active_version:'—')+'</strong><small>'+(d.pending_version?'待重建 v'+d.pending_version:'单一批次在途')+'</small></div>'+
  '<div><span>已收录样本</span><strong>'+fmt(d.rows)+'</strong><small>来源 '+esc(d.source)+'</small></div>'+
  '<div><span>接入凭据</span><strong>'+(d.token_valid?'有效':'已过期')+'</strong><small>'+(isSource?'源端第 '+d.token_id+' 号凭据':'人工导入无需凭据')+'</small></div></div>'+
  (isSource?positionLine(d):'')+
  (d.last_error?'<p class="warning">'+esc(d.last_error)+'</p>':'')+
  (d.rebuild_reason?'<p class="hint">'+esc(d.rebuild_reason)+'</p>':'')+
  (isSource?'<div class="sync-actions">'+
   '<label class="inline">本次最多翻页<input type="number" id="sync-pages" min="1" max="200" value="5"></label>'+
   '<button class="primary" id="sync-step" '+(writable()?'':'disabled')+'>分页取全量 / 继续 ↻</button>'+
   '<button class="button" id="sync-resume" '+(writable()?'':'disabled')+'>追平期间增删改并发布 →</button>'+
   '<button class="button" id="sync-incremental" '+(writable()?'':'disabled')+'>凭据增量同步</button>'+
   '<button class="button" id="sync-rebuild" '+(writable()?'':'disabled')+'>从全量重建</button>'+
   '<button class="button" id="sync-verify">对照源端校验</button></div>'+
   '<p class="hint">“分页取全量”每次只读取有限页并记录游标；翻页期间源端写入会在发布前按变更位置追平。中断后点“继续”从源端位置恢复，不会重复生成批次。</p>':'')+
  (verifyResult?'<div class="verify '+(verifyResult.clean?'ok':'dirty')+'"><strong>'+(verifyResult.clean?'已发布批次与源端一致':'与源端存在差异')+'</strong><p>已发布 v'+verifyResult.version+' 共 '+verifyResult.version_rows+' 条 · 源端 '+verifyResult.source_rows+' 条 · 缺失 '+verifyResult.missing_total+' · 多出 '+verifyResult.extra_total+' · 内容差异 '+verifyResult.changed_total+'</p></div>':'')+
  '<div class="section-title"><h2>批次版本</h2><span>版本一旦发布即固定，试验按创建时的版本计算</span></div>'+
  table([{key:'version',label:'版本'},{key:'status',label:'状态'},{key:'sync_mode',label:'同步方式'},{key:'row_count',label:'样本数'},{key:'source_position',label:'源端位置'},{key:'deletes',label:'撤销'},{key:'published_at',label:'发布时间'}],
    versions.map(v=>({...v,status:SyncStatus[v.status]||v.status,sync_mode:SyncMode[v.sync_mode]||v.sync_mode,published_at:v.published_at?date(v.published_at):'未发布'})),'尚无版本记录。')+
  '</section>';
}

function sourcePanel(s){
 if(!s)return '';
 const sample=(s.sample||[]).slice(0,8);
 const sid=esc(s.id);
 const last=(s.sample||[])[s.sample.length-1]||{};
 const days=(s.sample||[]).map(r=>r.day);
 const rowFor=key=>'<option value="'+esc(key)+'">'+esc(key)+'</option>';
 return '<section class="panel source-panel"><div class="section-title"><h2>模拟源写入 · '+esc(s.name)+'</h2><span>接入途中也可修改并核对</span></div>'+
  '<p class="hint">'+esc(s.label)+'。源端当前 '+s.rows+' 条样本，位置 '+s.seq+'；凭据'+(s.token_valid?'有效':'已过期')+'，每次重建会换新凭据。</p>'+
  '<div class="source-grid" data-source-id="'+sid+'"><form id="source-write" data-source-id="'+sid+'"><label>要修改的样本<select name="day" required>'+days.map(rowFor).join('')+'</select></label>'+
  '<div class="parameter-grid"><label>日产量<input name="units" type="number" step="any" value="'+esc(last.units??'')+'"></label><label>运行小时<input name="run_hours" type="number" step="any" value="'+esc(last.run_hours??'')+'"></label><label>温度℃<input name="temp_c" type="number" step="any" value="'+esc(last.temp_c??'')+'"></label><label>待机小时<input name="idle_hours" type="number" step="any" value="'+esc(last.idle_hours??'')+'"></label><label>耗电kWh<input name="kwh" type="number" step="any" value="'+esc(last.kwh??'')+'"></label></div>'+
  '<div class="inline-actions"><button type="submit" class="primary" '+(writable()?'':'disabled')+'>写入 / 修改此样本</button><button type="button" class="button" id="source-delete" '+(writable()?'':'disabled')+'>撤销此样本</button></div></form>'+
  '<div class="source-controls" data-source-id="'+sid+'"><label>每页条数<input id="source-page-size" type="number" min="1" max="200" value="'+s.page_size+'"></label><label>第几页模拟中断<input id="source-fail-page" type="number" min="1" value="'+(s.fail_at_page||'')+'" placeholder="留空不中断"></label><label>变更位置模拟中断<input id="source-fail-seq" type="number" min="1" value="'+(s.fail_at_seq||'')+'" placeholder="留空不中断"></label><div class="inline-actions"><button type="button" class="button small" id="source-save-config" '+(writable()?'':'disabled')+'>保存源端设置</button><button type="button" class="button small" id="source-expire" '+(writable()?'':'disabled')+'>让凭据过期</button><button type="button" class="button small" id="source-renew" '+(writable()?'':'disabled')+'>换发凭据</button></div></div></div>'+
  table([{key:'day',label:'日期'},{key:'units',label:'日产量'},{key:'run_hours',label:'运行小时'},{key:'temp_c',label:'温度℃'},{key:'idle_hours',label:'待机小时'},{key:'kwh',label:'耗电kWh'}],sample,'模拟源暂无可见样本。')+
  '<p class="hint">撤销为软删除并记录变更位置，后续任何全量或追平都不会让已撤销样本复活。</p></section>';
}

function intakeForms(allSources){
 return '<div class="intake-grid"><section class="panel"><div class="section-title"><h2>人工导入（一次成型）</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="5" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><button type="submit" class="primary" '+(writable()?'':'disabled')+'>校验并接入批次</button><p class="hint">人工导入没有源端可追平，适合一次性归档；持续改写请使用模拟源批次。</p></form></section>'+
 '<section class="panel"><div class="section-title"><h2>模拟源接入（可追平）</h2></div>'+
 '<form id="source-form"><label>新建独立模拟源<input name="name" required minlength="2" value="冲压一线 · 新模拟源"></label><button type="submit" class="primary" '+(writable()?'':'disabled')+'>创建模拟源</button></form>'+
 '<form id="source-batch-form"><label>选择模拟源<select name="simulated_source_id" required>'+allSources.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · '+s.rows+' 条</option>').join('')+'</select></label><label>接入批次名称<input name="name" required minlength="2" value="冲压一线 · 每日同步批次"></label><button type="submit" class="primary" '+(writable()?'':'disabled')+'>建立接入批次并待同步</button><p class="hint">建立后按“分页取全量”读取；首次齐全后才会对分析工作台开放。</p></form></section></div>';
}

export async function dataPage(){
 const [list,sourceList]=await Promise.all([datasets.list(),sources.list()]);
 workspace.datasets=list;workspace.sources=sourceList;
 const requestedId=workspace.selectedDataset;
 const selected=list.find(d=>d.id===requestedId)||list[0]||null;
 let detail=null,versions=[],verifyResult=null,source=null;
 if(selected){
   [detail,versions]=await Promise.all([datasets.get(selected.id),datasets.versions(selected.id)]);
   if(detail.source_id)source=sourceList.find(s=>s.id===detail.source_id)||await sources.get(detail.source_id);
 }
 workspace.currentSource=source;
 return heading('02 / DATA INTAKE','数据接入与批次追溯','独立模拟源分页取全量，再按变更位置追平期间的增删改，形成可归因、可核对的批次版本。','<button class="button" id="refresh-data">刷新状态 ↻</button>')+
  '<section class="panel overview-strip"><div class="section-title"><h2>接入状态总览</h2><span>'+list.length+' 个批次</span></div><div class="state-strip">'+
   Object.entries(SyncStatus).filter(([k])=>k!=='manual').map(([k,label])=>'<div><span>'+esc(label)+'</span><strong>'+list.filter(d=>d.sync_status===k).length+'</strong></div>').join('')+
   '<div><span>人工导入</span><strong>'+list.filter(d=>d.mode==='manual').length+'</strong></div></div></section>'+
  '<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>选择后查看接入详情</span></div><div class="batch-list">'+
   list.map(d=>'<button class="batch-item '+(selected&&d.id===selected.id?'active':'')+'" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+chip(d.sync_status)+' · '+fmt(d.rows)+' 条 · '+esc(d.source)+'</span><small>'+(d.mode==='source'?'源端位置 '+(d.source_position||0)+' / '+(d.source_head||0):'SHA256 '+esc((d.checksum||'').slice(0,18))+'…')+'</small></button>').join('')+
   (!list.length?'<div class="empty">尚无批次。</div>':'')+'</div></section>'+batchPanel(detail,versions,verifyResult)+'</div>'+
  sourcePanel(source)+intakeForms(sourceList)+
  '<section class="panel"><div class="section-title"><h2>已发布数据预览</h2><span>前 30 条 · 仅展示已发布版本</span></div><div id="data-preview">'+table(workspace.meta.columns,detail?.records?.slice(0,30)||[],'该批次尚未发布完整版本。')+'</div></section>';
}

export function bindData(refresh){
 let source='manual.json';
 const pages=()=>Number(document.querySelector('#sync-pages')?.value||0)||undefined;
 const run=async action=>{try{await action();await refresh();}catch(error){notify(error.message,true);}};
 document.querySelector('#refresh-data').onclick=refresh;
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{
   workspace.selectedDataset=Number(button.dataset.dataset);
   await run(async()=>{});
 });
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 const id=workspace.datasets.find(d=>d.id===workspace.selectedDataset)?.id||workspace.datasets[0]?.id;
 if(document.querySelector('#sync-step')){
   document.querySelector('#sync-step').onclick=()=>run(async()=>{const r=await datasets.sync(id,pages());workspace.lastSync=r;if(r.interrupted)notify(r.interrupted,true);else if(r.version.status==='synced')notify('全量已齐全并发布 v'+r.version.version);});
   document.querySelector('#sync-resume').onclick=()=>run(async()=>{const r=await datasets.resume(id);if(r.interrupted)notify(r.interrupted,true);else notify(r.unchanged?'源端无新变更，已是最新':'已追平并发布 v'+r.version.version);});
   document.querySelector('#sync-incremental').onclick=()=>run(async()=>{const r=await datasets.syncMode(id,'incremental');if(r.version.status==='needs_rebuild')notify('增量凭据已过期，需从全量重建；旧版仍可用',true);else notify(r.unchanged?'源端无新变更，已是最新':'增量追平完成，已发布 v'+r.version.version);});
   document.querySelector('#sync-rebuild').onclick=()=>run(async()=>{const r=await datasets.syncMode(id,'full',pages());if(r.interrupted)notify(r.interrupted,true);});
   document.querySelector('#sync-verify').onclick=()=>run(async()=>{const result=await datasets.verify(id);workspace.lastVerify=result;notify(result.clean?'已发布批次与源端一致':'发现差异，请查看校验结果',!result.clean);});
 }
 if(document.querySelector('#source-write')){
   submit(document.querySelector('#source-write'),async f=>{
     const day=f.get('day');
     const record={day,line:'冲压P01',units:Number(f.get('units')),run_hours:Number(f.get('run_hours')),temp_c:Number(f.get('temp_c')),idle_hours:Number(f.get('idle_hours')),kwh:Number(f.get('kwh'))};
     const r=await sources.ops(Number(document.querySelector('#source-write').dataset.sourceId),[{action:'upsert',record}]);
     notify('源端已写入位置 '+r.seq+'，可继续翻页验证追平');
     await refresh();
   });
   document.querySelector('#source-delete').onclick=async()=>{
     try{const day=document.querySelector('#source-write [name=day]').value;const r=await sources.ops(Number(document.querySelector('#source-write').dataset.sourceId),[{action:'delete',key:day}]);notify('已撤销 '+day+'，位置 '+r.seq);await refresh();}catch(error){notify(error.message,true);}
   };
   const sid=()=>Number(document.querySelector('.source-controls').dataset.sourceId);
   document.querySelector('#source-save-config').onclick=()=>run(async()=>{
     const value=key=>{const el=document.querySelector(key);return el&&el.value!==''?Number(el.value):undefined;};
     await sources.config(sid(),{page_size:value('#source-page-size'),fail_at_page:value('#source-fail-page'),fail_at_seq:value('#source-fail-seq')});
     notify('源端设置已保存');
   });
   document.querySelector('#source-expire').onclick=()=>run(async()=>{await sources.expireToken(sid());notify('凭据已过期，增量同步将要求全量重建');});
   document.querySelector('#source-renew').onclick=()=>run(async()=>{await sources.renewToken(sid());notify('已换发新凭据');});
 }
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});
 submit(document.querySelector('#source-form'),async f=>{const s=await sources.create({name:f.get('name')});notify('模拟源已创建，共 '+s.rows+' 条样本');await refresh();});
 submit(document.querySelector('#source-batch-form'),async f=>{await datasets.createFromSource({name:f.get('name'),simulated_source_id:Number(f.get('simulated_source_id'))});notify('接入批次已建立，请分页取全量');await refresh();});
}
