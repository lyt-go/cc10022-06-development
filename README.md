# 主数据清洗与黄金记录平台

面向多源主数据的匹配识别、冲突消解、合并清洗与黄金记录管理的主数据治理平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 来源系统注册 | `source_system` | 来源系统 | 系统编号、系统名称、系统类型 |
| 实体模型定义 | `entity_model` | 实体模型 | 模型编号、模型名称、业务域 |
| 匹配规则引擎 | `match_rule` | 匹配规则 | 规则编号、实体模型、匹配字段 |
| 疑似重复簇 | `dup_cluster` | 重复簇 | 簇编号、实体模型、簇大小 |
| 合并追溯日志 | `merge_log` | 合并记录 | 记录编号、黄金ID、来源记录 |
| 黄金记录管理 | `golden_record` | 黄金记录 | 黄金ID、实体模型、关联来源 |
| 字段标准化清洗 | `field_cleanse` | 清洗规则 | 规则编号、实体模型、目标字段 |
| 优胜策略配置 | `survivorship_rule` | 优胜策略 | 策略编号、实体模型、选择字段 |
| 数据入库规则 | `data_import_rule` | 入库规则 | 规则编号、来源系统、实体模型 |
| 批次导入管理 | `import_batch` | 导入批次 | 批次编号、来源系统、实体模型 |
| 记录级血缘 | `record_lineage` | 血缘记录 | 血缘编号、黄金ID、来源记录 |
| 主数据分发同步 | `mdm_sync` | 同步配置 | 配置编号、黄金实体、目标系统 |
| 黄金记录版本 | `mdm_version` | 版本记录 | 版本编号、黄金ID、版本号 |
| 自动匹配任务 | `auto_match_job` | 匹配任务 | 任务编号、实体模型、匹配规则 |
| 主数据质量统计 | `mdm_quality` | 质量统计 | 统计编号、实体模型、完备率 |
| 参考数据管理 | `mdm_reference` | 参考数据 | 数据编号、数据类别、标准编码 |
| 主数据查询接口 | `mdm_api` | 查询接口 | 接口编号、实体模型、查询字段 |
| 主数据治理看板 | `mdm_dashboard` | 看板配置 | 看板编号、看板名称、监控实体 |
| 补值返工视图 | `quality_rework` | 补值返工明细 | 返工编号、来源记录、待补字段、分区、负责人 |

## 补值返工链路

质量检查除了算完备率，还要把校验识别出的缺失字段追到**具体来源记录**，
形成可派发的补值返工明细。工作台入口是 `/quality_rework`。

- 缺字段证据来自 `source_record` 里的原始采集行（含采集分区、分区状态）。
  质量检查逐条比对必需字段，缺失就写一条返工明细，`来源记录 + 字段`
  是唯一键：同一份报告重复产出只更新证据，不新增明细。
- 客服源部分分区采集失败，因此分区状态为「未核分区」的记录只保留证据，
  不进入可派发清单；「已核分区」里待补的字段才是值班能派的事项。
- 补记原始行（如 CRM-41 的电话）后重算，完备率随之变化；字段标准化清洗
  复验改过的原始行，真的补齐了才关闭返工项并记下复验值。
- 报告编号决定轮次。已关闭的返工项不会被迟到的旧报告重新打开，
  也不会被旧报告退回更早轮次；重送旧报告后仍可按报告编号回查已完成事项。

主要接口：

| 接口 | 说明 |
| --- | --- |
| `GET /api/quality_rework/view?entity_model=customer` | 返工视图：已核 / 未核分区、可派发字段、派发清单 |
| `GET /api/quality_rework/{id}/trace` | 追溯单条事项的原始行快照、当前源行和待补字段 |
| `POST /api/quality_rework/dispatch` | 派发选中的已核分区事项 |
| `POST /api/quality_rework/revalidate` | 字段清洗复验原始行并关闭对应返工项 |
| `POST /api/source_record/{来源记录}/fields` | 补记原始行字段 |
| `POST /api/mdm_quality/recompute` | 重算历史检查数据并刷新返工明细 |
| `POST /api/mdm_quality/reports` | 接收质量检查报告（同轮去重、旧报告不重开） |
| `GET /api/quality_rework/reports/{报告编号}` | 按报告回查返工明细，含已关闭事项 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数仓与数据湖
