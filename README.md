# LeakGuard · 训练/评测拆分来源核查服务

在模型训练实验启动前，核查**训练集与评测集不会共享同一来源对象（主体）**，并满足时间分界条件。
本项目不训练任何真实模型，只负责：生成拆分方案 → 报告冲突与比例差异 → 确认后持久化清单与随机种子。

- **后端**：FastAPI + pandas + scikit-learn（`StratifiedShuffleSplit`，种子化）
- **存储**：PostgreSQL（样本清单、来源关系、拆分清单、随机种子与统计）
- **前端**：Angular 19（参数设置、核查结论、逐样本归属与冲突原因、已保存方案）

## 核查规则（关键语义）

1. **主体隔离**：按“主体”而非样本拆分，一个已知主体只出现在训练集 / 评测集 / 隔离区之一。
2. **时间分界**：训练集严格只含分界日之前的样本；分界后才出现的主体强制归入评测。
3. **跨月份主体**：同一主体在分界前后都有样本时，默认整体**隔离**；
   也可强制归入一侧，但违反时间条件的计数会被如实标红（而不是隐藏）。
4. **派生样本继承身份**：裁切 / 增强样本沿 `source_ref` 链回溯到原始样本，继承其主体和归属。
5. **未知来源单独提示**：来源引用不存在、来源成环、原始样本无主体——全部隔离并计数。
   **未知关系只能隔离，不能被证明“泄漏已消除”**，页面和 API 均如此表述。
6. **罕见类别**：只有一个主体承载的类别无法分层，使用种子化逐类分配并显式报告
   实际评测比例与目标的差异（逐类别 + 总体）。

## 演示场景（16 个样本，cutoff = 2024-06-01）

| 对象 | 场景 | 预期 |
|---|---|---|
| S-101 / S-102 | 同一主体 5 月与 7 月都有样本 | 跨时间分界 → 隔离 |
| S-103…S-107 | 仅分界前 | 种子化分层进入训练/评测 |
| S-108 | 仅分界后（8 月） | 强制评测 |
| S-109 | 罕见类别 `rare-anomaly` 唯一承载者 | 无法分层，报告比例差异 |
| CROP-001 | IMG-005 的裁切 | 继承 S-103 身份与归属 |
| CROP-002 | 引用已删除来源 `IMG-GONE-999` | 来源缺失 → 隔离，不宣称安全 |
| CROP-003/004 | 来源链成环 | 无法溯源 → 隔离 |
| IMG-012 | 无主体原始样本 | 缺少主体 → 隔离 |

## 启动

```bash
# 1) PostgreSQL（普通沙箱可用内嵌二进制，正式环境改用自带 PG 并设置 DATABASE_URL）
scripts/start-db.sh

# 2) 后端（自动建表）
scripts/start-api.sh                     # http://127.0.0.1:8000  （/docs 为 Swagger）

# 3) 前端（开发模式，已配置 /api 代理到 8000）
cd frontend && npm install && npm start  # http://127.0.0.1:4200
```

生产构建：`cd frontend && npm run build`，后端会自动托管
`frontend/dist/leakguard/browser`。

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/demo/reset` | 重置并载入 16 个演示样本 |
| GET | `/api/samples` | 样本清单与来源引用 |
| POST | `/api/samples` | 新增样本（来源引用可为悬空，便于标记） |
| POST | `/api/splits/preview` | 参数：`cutoff_date`、`subject_field=subject_id`、`target_eval_ratio`、`seed`、`cutoff_policy` |
| POST | `/api/splits/confirm` | 确认并持久化清单 + 种子 |
| GET | `/api/splits` / `/api/splits/{id}` | 方案列表 / 逐样本归属与原因 |

返回中的 `stats.assertions` 只报告**可验证**的结论：

- `subject_isolation`：已知主体没有跨集合；
- `train_before_cutoff_only`：训练集严格在分界前；
- `unknown_provenance_quarantined`：所有来源未知样本均已隔离（≠ 已证明无泄漏）。

## 测试

```bash
cd backend && python3 -m pytest tests -q
```

13 项测试覆盖：主体跨月份隔离、派生身份继承、缺来源/成环/无主体隔离、
时间条件、罕见类别比例偏差、种子可复现、不安全策略下的违规如实上报。
