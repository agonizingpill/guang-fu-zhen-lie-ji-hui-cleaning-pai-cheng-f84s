from datetime import date,datetime
from sqlalchemy import String,Float,Boolean,Integer,ForeignKey,JSON,CheckConstraint,Date,DateTime,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class BatchPlan(Base):
    __tablename__='batch_plans'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(40),unique=True)
    work_date:Mapped[date]=mapped_column(Date)
    state:Mapped[str]=mapped_column(String(16),default='preview')
    objective_kw:Mapped[float]=mapped_column(Float,default=0)
    basis:Mapped[dict]=mapped_column(JSON)
    created_by:Mapped[str]=mapped_column(String(120))
    confirmed_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    confirmed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class BatchPlanItem(Base):
    __tablename__='batch_plan_items'
    __table_args__=(CheckConstraint('minutes>0 AND water_liters>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    plan_id:Mapped[int]=mapped_column(ForeignKey('batch_plans.id'))
    mission_id:Mapped[int]=mapped_column(ForeignKey('wash_missions.id'))
    permit_id:Mapped[int]=mapped_column(ForeignKey('work_permits.id'))
    survey_id:Mapped[int]=mapped_column(ForeignKey('soiling_surveys.id'))
    block_id:Mapped[int]=mapped_column(ForeignKey('array_blocks.id'))
    crew_id:Mapped[int]=mapped_column(ForeignKey('wash_crews.id'))
    selected:Mapped[bool]=mapped_column(Boolean,default=False)
    minutes:Mapped[int]=mapped_column(Integer)
    water_liters:Mapped[float]=mapped_column(Float)
    predicted_loss:Mapped[float]=mapped_column(Float)
    margin_kw:Mapped[float]=mapped_column(Float)
    conservative_kw:Mapped[float]=mapped_column(Float)
    reason:Mapped[str]=mapped_column(String(240),default='')
