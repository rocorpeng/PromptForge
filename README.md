# PromptForge Local

PromptForge 是一个本地运行的 AI 应用生成 Demo：用户用自然语言描述业务工具，本地 Agent 将需求转换为受控 `AppSpec`，前端根据规格动态渲染表单、列表、筛选和数据操作界面。

业务数据和版本数据均保存在本地 SQLite 文件中。需求到 `AppSpec` 的转换由 **DeepSeek** 完成，未配置 API Key 时自动回退到内置的本地规则生成器。

## 已实现

- 三栏生成工作台：项目列表、Agent 对话、应用实时预览
- DeepSeek 驱动的需求理解与 `AppSpec` 生成（可回退本地规则生成器）
- 动态字段：文本、长文本、数字、日期、下拉、布尔值
- 动态视图：表格/卡片、搜索、筛选
- 业务记录新增、编辑、删除
- AppSpec 版本历史与恢复
- 项目发布与公开运行态 `?public=<slug>`
- 文件型 SQLite 持久化

## 目录

- `backend/`：FastAPI API、SQLite 数据库、DeepSeek 生成器
- `frontend/`：Vite + React + TypeScript 前端
- `frontend-sso-backup/`：早期复杂模板备份，不参与当前版本运行

## 启动后端

```bash
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python main.py
```

后端默认地址：`http://localhost:8000`  
OpenAPI 文档：`http://localhost:8000/api/docs`

数据库文件为 `backend/promptforge.db`。首次启动会自动建表并写入示例项目与示例记录。

### 配置 DeepSeek

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxxx
```

Key 在 <https://platform.deepseek.com/api_keys> 申请。默认模型 `deepseek-flash`（以 `GET /models` 返回为准；官方文档写的 `deepseek-v4-flash` 与实际模型名不一致，旧的 `deepseek-chat` / `deepseek-reasoner` 已于 2026/07/24 废弃）。其余可调项见 `backend/.env.example`。

验证是否生效：

```bash
curl -s http://localhost:8000/api/health   # 关注 llm.configured
```

未配置 Key 或调用失败时不会报错中断，生成接口会返回 `engine: "local"` 并在对话里说明回退原因。

## 启动前端

打开另一个终端：

```bash
cd frontend
pnpm install
pnpm run dev -- --host 127.0.0.1
```

前端默认地址：`http://localhost:5173`

> 请使用 `http://localhost:5173` 访问。后端 CORS 白名单只包含 `localhost`，用 `127.0.0.1:5173` 打开会导致接口预检失败。

如果后端地址不是默认值，请创建 `frontend/.env.local`：

```env
VITE_API_BASE_URL=http://localhost:8000
```

## 验证

```bash
# 前端类型检查
cd frontend && pnpm run lint

# 前端生产构建
cd frontend && pnpm run build

# 后端健康检查
curl http://localhost:8000/api/health
```

## 当前边界

- 生成的 `AppSpec` 受前端渲染能力约束：字段类型仅支持文本、长文本、数字、日期、下拉、布尔值，视图仅支持表格与卡片。
- `colorRule` 只支持「某字段等于某个值」的相等判断（`view.colorRule.color` 支持 green / red / amber / blue / gray）。像「库存低于安全库存」这类跨字段的大小比较无法表达，模型会退化成增加一个状态枚举字段来近似。
- 当前为单机、单用户 Demo，未实现登录、权限与多人协作。
- SQLite 适合当前本地原型；后续可将数据访问层替换为 PostgreSQL/Supabase。# PromptForge

# PromptForge
# PromptForge
# PromptForge
