from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor,admin
from .batch_models import BatchPlan
from .operations_schemas import BatchPreviewInput
from . import batch_service
router=APIRouter(prefix='/batch-plans')
@router.get('')
def plans(u=Depends(current),db=Depends(session)):return db.scalars(select(BatchPlan).order_by(BatchPlan.id.desc())).all()
@router.get('/{key}')
def plan_detail(key:int,u=Depends(current),db=Depends(session)):return batch_service.detail(db,key)
@router.post('/preview')
def plan_preview(b:BatchPreviewInput,u=Depends(editor),db=Depends(session)):return batch_service.preview(db,b,u)
@router.post('/{key}/confirm')
def plan_confirm(key:int,u=Depends(admin),db=Depends(session)):return batch_service.confirm(db,key,u)
