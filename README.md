# LeakGuard — 训练/评测样本拆分核查

在启动实验前，由系统（而非人工）确认训练集与评测集**不共享同一来源对象**。

- **Angular**：展示样本分组、分桶、冲突原因与逐样本归属
- **FastAPI + pandas + scikit-learn**：按时间分界/主体字段/目标类别比例生成拆分方案
- **PostgreSQL**：保存样本清单、来源（派生）关系、拆分方案与随机种子
- 不训练任何真实模型

## 核查规则（与需求逐条对应）

1. **主体隔离**：以「原始来源主体」为分组单位，同一主体只出现在 train 或 eval 中的一个。
2. **来源继承**：裁切 / 增强等派生样本沿 `parent_id` 链回溯，继承链顶端原始样本的主体身份（支持多跳）。
3. **缺来源单独提示**：主体为空、父样本缺失（断链）、来源链成环的样本进入 `unresolved` 桶，**不参与拆分**，以 error 级冲突列出。
4. **时间分界**：
   - `hard`（默认）：早于 cutoff → train，不早于 cutoff → eval；主体横跨分界两侧时按
     `train_lock`（保留训练侧、剔除未来样本）或 `eval_lock`（反之）处理，被剔除样本进 `excluded` 桶并记录原因。
   - `grouped_stratify`：用 sklearn `StratifiedGroupKFold` 在保持主体完整的前提下逼近目标比例，但会标记所有横跨时间分界的组（随机次序不保证时间先后）。
5. **比例差异**：逐类别报告 目标评测占比 / 实际评测占比 / 差值；超过 5% 容忍度或完全无法达成（如罕见类别没有未来样本）时显式告警，不伪造平衡。
6. **确认后持久化**：预览 → 人工检查 → 确认；每次运行的参数、种子、逐样本归属与冲突均落库，可通过 `GET /api/splits/{id}` 回查。
7. **泄漏措辞**：存在 unresolved 样本时，结论明确写「关系未知，不能宣称泄漏已消除」，仅对来源已确认的样本保证隔离。

## 一键启动（PostgreSQL + 后端 + 前端）

```bash
docker compose up --build
# 前端 http://localhost:4200   后端 http://localhost:8000/docs
```

后端容器启动时自动建表并导入演示数据（15 个样本，见 `backend/app/seed_demo.py`）。

## 本地开发

```bash
# 后端（本环境已预置虚拟环境 /workspace/.venv，可直接使用）
cd backend
python -m venv .venv && . .venv/bin/activate   # 或 source /workspace/.venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./dev.db"        # 无本地 PostgreSQL 时用 SQLite 开发
python -m app.seed_demo
uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm start          # http://localhost:4200, /api 代理到 :8000
```

## 自动化验证

```bash
cd backend

# 11 项端到端断言：主体跨月份隔离 / 罕见类别比例不可达 / 派生样本缺来源 / 种子持久化
python verify_demo.py

# FastAPI 接口级测试（9 个用例，含两种时间模式与确认流程）
python -m pytest tests/ -q
```

## 验证场景说明（verify_demo.py）

| 场景 | 数据 | 预期 |
| --- | --- | --- |
| 主体跨月份 | `subj-A` 同时有 7 月与 8 月样本，且 8 月样本还有裁切件 | train_lock：7 月样本留 train，8 月样本（含其裁切件）进 excluded，**eval 中不出现 subj-A** |
| 罕见类别 | `rare_anomaly` 仅 1 个主体且都在分界前 | eval=0，实际 0% vs 目标 50%，差异 −50% 并告警 |
| 派生样本缺来源 | `x-crop` 的 `parent_id=ghost-origin` 不存在 | 进 unresolved，error 冲突，结论声明「关系未知，不能宣称泄漏已消除」 |

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/samples` | 样本清单 |
| POST | `/api/samples` / `/api/samples/bulk` | 录入样本（支持派生链） |
| POST | `/api/splits/preview` | 生成拆分（不改变已确认记录），返回分桶/比例/冲突/逐样本原因 |
| POST | `/api/splits/{id}/confirm` | 确认并固化清单与种子 |
| GET | `/api/splits` / `/api/splits/{id}` | 历史运行 / 逐样本归属与冲突原因 |

## 数据模型

- `samples`：`id, label, captured_at, subject_id, parent_id(→samples.id), kind(original/crop/augment)`
- `split_runs`：`cutoff, subject_field, target_ratios(JSON), seed, time_mode, straddle_policy, status, summary(JSON)`
- `assignments`：每次拆分中每个样本的 `bucket / root_subject / reason`
- `conflicts`：`straddles_cutoff`、`unresolved_dangling_parent`、`unresolved_origin_without_subject`、`unresolved_provenance_cycle`、`stratify_fallback`
