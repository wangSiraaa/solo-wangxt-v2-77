"""FastAPI application: sample manifest, split preview/confirm, run history."""
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud
from .database import get_db, init_db
from .models import Sample
from .schemas import (
    SampleIn,
    SampleOut,
    SplitRequest,
    SplitResult,
)

app = FastAPI(
    title="LeakGuard — 训练/评测样本拆分核查服务",
    description=(
        "按时间分界与主体字段生成训练/评测拆分：同一主体只落在一个集合，"
        "派生样本继承原始来源身份，缺失来源单独隔离提示，确认后持久化清单与随机种子。"
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/samples", response_model=list[SampleOut])
def list_samples(db: Session = Depends(get_db)):
    return list(db.execute(select(Sample).order_by(Sample.captured_at, Sample.id)).scalars())


@app.post("/api/samples", response_model=SampleOut, status_code=201)
def create_sample(payload: SampleIn, db: Session = Depends(get_db)):
    if payload.parent_id and not crud.parent_id_exists(db, payload.parent_id, exclude=payload.id):
        raise HTTPException(
            status_code=422,
            detail=f"parent_id={payload.parent_id} 在清单中不存在；"
            "如要表达来源缺失，请使用 demo 的孤立派生样本（不设置 parent_id 且不带 subject_id）。",
        )
    sample = crud.upsert_sample(db, payload)
    db.commit()
    db.refresh(sample)
    return sample


@app.post("/api/samples/bulk", status_code=201)
def bulk_create(payloads: list[SampleIn], db: Session = Depends(get_db)) -> dict:
    # Bulk imports are accepted as-is: dangling parent references are kept and
    # surfaced as unresolved provenance at split time (the manifest may have
    # arrived before its parent records). Duplicate ids in the same payload are
    # still rejected to keep the upsert semantics deterministic.
    ids = [p.id for p in payloads]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="批量提交中存在重复的样本 id。")
    for p in payloads:
        crud.upsert_sample(db, p)
    db.commit()
    return {"created": len(payloads)}


@app.delete("/api/samples/{sample_id}", status_code=204)
def delete_sample(sample_id: str, db: Session = Depends(get_db)):
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="sample not found")
    db.delete(sample)
    db.commit()


@app.post("/api/splits/preview", response_model=SplitResult)
def preview_split(req: SplitRequest, db: Session = Depends(get_db)):
    _, result = crud.run_split(db, req)
    db.commit()
    return _serialize(result)


@app.post("/api/splits/{run_id}/confirm", response_model=SplitResult)
def confirm_split(run_id: int, db: Session = Depends(get_db)):
    from .models import SplitRun

    run = db.get(SplitRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="split run not found")
    if run.status == "confirmed":
        raise HTTPException(status_code=409, detail="该拆分已确认，不能重复确认。")
    crud.confirm_run(db, run)
    db.commit()
    return _serialize(crud.serialize_run(run))


@app.get("/api/splits", response_model=list[dict])
def list_runs(db: Session = Depends(get_db)):
    from .models import SplitRun

    runs = db.execute(select(SplitRun).order_by(SplitRun.id.desc())).scalars()
    out = []
    for run in runs:
        item = {k: v for k, v in crud.serialize_run(run).items() if k not in ("assignments", "conflicts")}
        out.append(item)
    return out


@app.get("/api/splits/{run_id}", response_model=SplitResult)
def get_run(run_id: int, db: Session = Depends(get_db)):
    from .models import SplitRun

    run = db.get(SplitRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="split run not found")
    return _serialize(crud.serialize_run(run))


def _serialize(result: dict) -> dict:
    # Pass ratios through untouched: actual/diff stay None for classes with no
    # splittable samples so the UI can render "—" instead of a fake 0%.
    return result
