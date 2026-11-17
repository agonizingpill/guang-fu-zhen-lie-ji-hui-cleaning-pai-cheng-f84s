import {field,sync} from '../store.js';
import {request,identity} from '../api.js';
import {lead,blockName} from '../components/field.js';
import {safe,fixed,dataFrom,message,localTime} from '../utils.js';
import {PLAN_STATES} from '../constants.js';
const pbadge=s=>`<span class="badge ${safe(s)}">${safe(PLAN_STATES[s]||s)}</span>`;
const crewCode=id=>field.crews.find(c=>c.id===id)?.code||'未知班组';
async function loadDetail(id){field.planDetail=await request('/batch-plans/'+id);}
function detailView(d,admin){
  const p=d.plan,basis=p.basis||{},conflicts=basis.conflicts||[];
  const items=[...d.items].sort((a,b)=>(b.selected-a.selected)||(b.conservative_kw-a.conservative_kw));
  return `<div class="mission-title"><div><span class="code">${safe(p.code)} / ${p.work_date}</span><h2>组合排程批次</h2>${pbadge(p.state)}</div><span class="note">预览 ${safe(p.created_by)} · ${localTime(p.created_at)}<br>确认 ${safe(p.confirmed_by||'—')}${p.confirmed_at?' · '+localTime(p.confirmed_at):''}</span></div>
  <div class="cols four"><div><span class="note">入选任务</span><div class="reading">${d.items.filter(i=>i.selected).length}<small> / ${d.items.length}项候选</small></div></div><div><span class="note">批次保守收益</span><div class="reading">${fixed(p.objective_kw)}<small> kW</small></div></div><div><span class="note">校准边际 q90</span><div class="reading">${fixed(basis.margin_kw,2)}<small> kW</small></div></div><div><span class="note">独立留出MAE</span><div class="reading">${fixed(basis.holdout_mae_kw,2)}<small> kW</small></div></div></div>
  ${conflicts.length?`<div class="rule">确认时候选条件已变化，整批拒绝（未扣水、未签许可）：<br>${conflicts.map(c=>safe(c)).join('<br>')}</div>`:''}
  <div class="tablewrap"><table><thead><tr><th>任务</th><th>阵列</th><th>班组 / 工时</th><th>计划用水</th><th>预测损失</th><th>校准边际</th><th>保守收益</th><th>入选与落选依据</th></tr></thead><tbody>${items.map(it=>`<tr class="${it.selected?'picked':''}"><td>WASH-${it.mission_id}</td><td>${safe(blockName(it.block_id))}</td><td>${safe(crewCode(it.crew_id))} · ${it.minutes}分钟</td><td>${fixed(it.water_liters,0)} L</td><td>${fixed(it.predicted_loss)} kW</td><td>−${fixed(it.margin_kw,2)} kW</td><td>${fixed(it.conservative_kw)} kW</td><td>${safe(it.reason)}</td></tr>`).join('')}</tbody></table></div>
  <details class="evidence"><summary>查看本批采用的预测依据</summary><p class="note">${safe(basis.method||'')} · 参考样本SHA ${safe((basis.model_sha256||'').slice(0,16))}…<br>训练 ${basis.train_rows} / 独立留出 ${basis.test_rows} 条 · 训练MAE ${fixed(basis.train_mae_kw,3)} kW · 留出MAE ${fixed(basis.holdout_mae_kw,3)} kW<br>${safe(basis.calibration||'')}（q${Math.round((basis.residual_quantile||0)*100)}边际 ${fixed(basis.margin_kw,3)} kW）<br>预览时当日剩余工时：${Object.entries(basis.crew_remaining_minutes||{}).map(([k,v])=>safe(k)+' '+v+'分钟').join(' / ')||'—'}</p></details>
  <div class="actionbar">${p.state==='preview'?`<button id="plan-confirm" class="warm" ${admin?'':'disabled'}>主管确认：整批签许可并派工</button>`:''}${p.state==='dispatched'?`<button id="goto-missions" class="primary">进入已派工任务</button>`:''}${p.state==='conflict'?`<button id="plan-repreview" class="primary">按当前条件重新预览</button>`:''}</div>
  ${p.state==='preview'?'<div class="rule">确认时重新核验全部候选：与单任务派工、撤销许可并发导致条件变化的，整批拒绝，不静默换选、不部分扣水；重试不会重复派工或扣额。</div>':''}`;
}
export function render(){
  const admin=identity().role==='admin',edit=identity().role!=='viewer';
  const today=new Date().toISOString().slice(0,10);
  return lead('BATCH SCHEDULING','按保守收益，排定一整天的清洗组合','高估损会挤占班组工时：以独立留出残差校准估损下界，对当日草稿任务做组合优化；预览不占资源，主管确认才整批签许可并派工。')+`<div class="mission-layout"><aside class="mission-list"><section class="surface planbox"><h3>新建组合预览</h3><form id="plan-preview"><label>作业日期<input name="work_date" type="date" value="${today}" required></label><button class="primary" ${edit?'':'disabled'}>生成组合预览</button></form><p class="note">候选＝当日草稿许可对应的草稿任务；请先在班组作业许可页申请许可。预览不占用工时与水额。</p></section>${field.plans.length?field.plans.map(p=>`<button data-plan="${p.id}" class="${field.planDetail&&field.planDetail.plan.id===p.id?'selected':''}"><span class="code">${safe(p.code)}</span><h3>${p.work_date} · 保守收益 ${fixed(p.objective_kw)} kW</h3>${pbadge(p.state)}</button>`).join(''):'<div class="empty">尚无组合排程预览。</div>'}</aside><section class="surface">${field.planDetail?detailView(field.planDetail,admin):'<div class="empty">选择左侧批次查看入选与落选依据，或按日期生成新预览。</div>'}</section></div>`;
}
export function bind(rerender){
  document.querySelectorAll('[data-plan]').forEach(b=>b.onclick=async()=>{try{await loadDetail(Number(b.dataset.plan));rerender();}catch(e){message(e.message);}});
  const pf=document.querySelector('#plan-preview');
  if(pf)pf.onsubmit=async e=>{e.preventDefault();try{const d=await request('/batch-plans/preview','POST',dataFrom(e.target));await sync();await loadDetail(d.plan.id);rerender();message('组合预览已生成，未占用任何资源');}catch(err){message(err.message);}};
  const cf=document.querySelector('#plan-confirm');
  if(cf)cf.onclick=async()=>{const id=field.planDetail.plan.id;try{const d=await request('/batch-plans/'+id+'/confirm','POST');await sync();await loadDetail(id);rerender();message('已整批签许可并派工，水量已扣减');}catch(err){await sync();try{await loadDetail(id);}catch(e){}rerender();message(err.message);}};
  const gm=document.querySelector('#goto-missions');
  if(gm)gm.onclick=()=>{location.hash='missions';};
  const rp=document.querySelector('#plan-repreview');
  if(rp)rp.onclick=async()=>{try{const d=await request('/batch-plans/preview','POST',{work_date:field.planDetail.plan.work_date});await sync();await loadDetail(d.plan.id);rerender();message('已按当前条件重新预览');}catch(err){message(err.message);}};
}
