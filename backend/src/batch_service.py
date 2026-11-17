import secrets
from collections import defaultdict
from datetime import datetime
from sqlalchemy import select,func
from fastapi import HTTPException
from .models import ArrayBlock,SoilingSurvey,WashMission
from .operations_models import WashCrew,WorkPermit
from .batch_models import BatchPlan,BatchPlanItem
from .field_service import require,audit
from .power_model import train_reference,conservative_loss
from .batch_optimizer import optimize

def _occupied(db,crew_id,work_date):
    return db.scalar(select(func.coalesce(func.sum(WorkPermit.minutes),0)).where(WorkPermit.crew_id==crew_id,WorkPermit.work_date==work_date,WorkPermit.state.in_(['signed','used'])))

def detail(db,key):
    plan=require(db,BatchPlan,key)
    items=db.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id==plan.id).order_by(BatchPlanItem.id)).all()
    return {'plan':plan,'items':items}

def preview(db,body,user):
    work_date=body.work_date
    _,evidence=train_reference()
    margin=evidence['holdout_residual_q90_kw']
    crews=db.scalars(select(WashCrew).order_by(WashCrew.id)).all()
    crew_map={c.id:c for c in crews}
    remaining={c.id:c.max_daily_minutes-_occupied(db,c.id,work_date) for c in crews}
    items=[];cands=[]
    drafts=db.scalars(select(WashMission).where(WashMission.status=='draft').order_by(WashMission.id)).all()
    for m in drafts:
        p=db.scalar(select(WorkPermit).where(WorkPermit.mission_id==m.id))
        if not p or p.work_date!=work_date:continue
        s=db.get(SoilingSurvey,m.survey_id);b=db.get(ArrayBlock,s.block_id)
        cons=conservative_loss(s.predicted_loss or 0,evidence)
        item={'mission_id':m.id,'permit_id':p.id,'survey_id':s.id,'block_id':b.id,'crew_id':p.crew_id,'minutes':p.minutes,'water_liters':m.water_liters,'predicted_loss':s.predicted_loss or 0,'margin_kw':margin,'conservative_kw':cons,'selected':False,'reason':''}
        crew=crew_map.get(p.crew_id)
        if p.state=='signed':item['reason']='落选：许可已签发并占用工时，请单独派工或撤销后重排'
        elif p.state!='draft':item['reason']='落选：许可已撤销，需重新申请'
        elif s.state!='assessed':item['reason']='落选：巡测未完成评估或已失效'
        elif b.cleaning_state=='washing':item['reason']='落选：阵列清洗执行中'
        elif m.water_liters>b.water_liters or m.water_liters>m.available_liters:item['reason']=f'落选：计划用水{m.water_liters:g}L超阵列可用{min(b.water_liters,m.available_liters):g}L'
        elif not crew or not crew.active:item['reason']='落选：班组已停用'
        elif not p.isolation:item['reason']='落选：许可未完成电气隔离'
        elif p.wind_mps>10:item['reason']='落选：许可阵风超10m/s，待修订'
        elif p.minutes>remaining[p.crew_id]:item['reason']=f'落选：{crew.code}当日剩余工时{remaining[p.crew_id]}分钟不足'
        elif cons<=0:item['reason']='落选：校准后保守收益为0'
        else:cands.append({'key':m.id,'crew':p.crew_id,'minutes':p.minutes,'benefit':cons,'group':b.id,'item':item})
        items.append(item)
    picked,_=optimize(cands,remaining)
    used=defaultdict(int)
    for c in cands:
        if c['key'] in picked:used[c['crew']]+=c['minutes']
    for c in cands:
        it=c['item']
        if c['key'] in picked:
            it['selected']=True;it['reason']=f"入选：保守收益{it['conservative_kw']:g}kW · {crew_map[c['crew']].code}占用{c['minutes']}分钟"
            continue
        clash=next((o for o in cands if o['group']==c['group'] and o['key'] in picked),None)
        if clash:it['reason']=f"落选：同阵列互斥，组合改选WASH-{clash['key']}后总收益更高"
        elif c['minutes']>remaining[c['crew']]-used[c['crew']]:it['reason']=f"落选：{crew_map[c['crew']].code}当日工时让位于保守收益更高的组合（剩余{remaining[c['crew']]-used[c['crew']]}分钟）"
        else:it['reason']='落选：组合优化下总保守收益不及入选方案'
    objective=round(sum(c['benefit'] for c in cands if c['key'] in picked),4)
    basis={'model_sha256':evidence['sha256'],'method':evidence['method'],'train_rows':evidence['train_rows'],'test_rows':evidence['test_rows'],'train_mae_kw':evidence['train_mae_kw'],'holdout_mae_kw':evidence['holdout_mae_kw'],'residual_quantile':0.9,'margin_kw':margin,'calibration':'保守收益=max(0, 预测损失−独立留出残差q90)','crew_remaining_minutes':{crew_map[k].code:v for k,v in remaining.items()}}
    plan=BatchPlan(code=f'BP-{work_date:%Y%m%d}-{secrets.token_hex(2).upper()}',work_date=work_date,state='preview',objective_kw=objective,created_by=user.email,basis=basis)
    db.add(plan);db.flush()
    for it in items:db.add(BatchPlanItem(plan_id=plan.id,**it))
    audit(db,user,f'组合排程预览{plan.code}：{len(picked)}/{len(items)}项入选，保守收益{objective}kW')
    db.commit();return detail(db,plan.id)

def confirm(db,key,user):
    plan=require(db,BatchPlan,key,True)
    if plan.state=='dispatched':return detail(db,key)
    if plan.state=='conflict':raise HTTPException(409,'该批次已因冲突待重排，请按当前条件重新预览')
    items=db.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id==plan.id,BatchPlanItem.selected.is_(True)).order_by(BatchPlanItem.mission_id)).all()
    if not items:raise HTTPException(409,'批次无入选任务，请重新预览')
    problems=[];locked=[]
    # 与单任务派工/撤销许可并发时，按固定顺序加锁并重新核验全部候选条件。
    for it in items:
        m=require(db,WashMission,it.mission_id,True)
        s=require(db,SoilingSurvey,m.survey_id,True)
        b=require(db,ArrayBlock,s.block_id,True)
        p=require(db,WorkPermit,it.permit_id,True)
        if m.status!='draft':problems.append(f'WASH-{m.id}任务状态已变为{m.status}')
        if s.state!='assessed':problems.append(f'WASH-{m.id}巡测状态已变为{s.state}')
        if p.state!='draft':problems.append(f'WASH-{m.id}许可已变为{p.state}')
        if p.minutes!=it.minutes or p.crew_id!=it.crew_id or p.work_date!=plan.work_date:problems.append(f'WASH-{m.id}许可已修订，与预览快照不一致')
        if m.water_liters!=it.water_liters:problems.append(f'WASH-{m.id}计划用水已修订')
        if b.cleaning_state=='washing':problems.append(f'WASH-{m.id}阵列清洗执行中')
        if m.water_liters>b.water_liters or m.water_liters>m.available_liters:problems.append(f'WASH-{m.id}阵列水额不足')
        if not p.isolation or p.wind_mps>10:problems.append(f'WASH-{m.id}许可安全条件不满足')
        locked.append((it,m,s,b,p))
    if len({b.id for it,m,s,b,p in locked})!=len(locked):problems.append('同阵列互斥被破坏')
    need=defaultdict(int)
    for it,m,s,b,p in locked:need[p.crew_id]+=p.minutes
    for crew_id in sorted(need):
        c=require(db,WashCrew,crew_id,True)
        if not c.active:problems.append(f'班组{c.code}已停用');continue
        occupied=_occupied(db,crew_id,plan.work_date)
        if occupied+need[crew_id]>c.max_daily_minutes:problems.append(f'班组{c.code}当日工时不足：已占{occupied}+本批{need[crew_id]}>{c.max_daily_minutes}分钟')
    if problems:
        plan.state='conflict';plan.basis={**plan.basis,'conflicts':problems}
        audit(db,user,f'组合排程{plan.code}确认重核验发现{len(problems)}项冲突，整批拒绝')
        db.commit();raise HTTPException(409,'候选条件已变化，整批拒绝：'+'；'.join(problems))
    now=datetime.utcnow();segments=[]
    for it,m,s,b,p in locked:
        p.state='signed';p.signed_by=user.email
        p.state='used'
        m.available_liters=b.water_liters
        b.water_liters=round(b.water_liters-m.water_liters,3);b.cleaning_state='washing'
        m.status='dispatched';m.dispatched_at=now;s.state='scheduled'
        segments.append(f'WASH-{m.id}扣{m.water_liters:g}L')
    plan.state='dispatched';plan.confirmed_by=user.email;plan.confirmed_at=now
    audit(db,user,f'组合排程{plan.code}整批签发许可并派工{len(locked)}项：'+'，'.join(segments))
    db.commit();return detail(db,key)
