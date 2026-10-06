# PromptForge Local Backend

基于 FastAPI 0.67、Pydantic v1 和 Python 标准库 `sqlite3` 的本地后端。服务不要求 JWT 或登录，数据持久化到当前目录的 `promptforge.db`。

## 本地运行

```bash
python3 main.py
```

默认监听 `8000` 端口，可通过 `_BYTEFAAS_RUNTIME_PORT` 调整。OpenAPI 文档位于 `/api/docs`。CORS 已允许 `http://localhost:5173`。

> `run.sh` 是 scaffold 的受保护入口，保持原样。

## 生成器：DeepSeek

`POST /api/projects/{project_id}/generate` 优先调用 DeepSeek 生成 `AppSpec`，失败时自动回退到本地规则生成器，因此**没有 API Key 也能用**，只是生成的字段和视图质量明显更差。

配置方式：复制 `.env.example` 为 `.env`（`.env` 已在 `.gitignore` 中）并填入 Key。

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxxx
```

| 环境变量                | 默认值                        | 说明                                                                                  |
| ------------------- | -------------------------- | ----------------------------------------------------------------------------------- |
| `DEEPSEEK_API_KEY`  | 空                          | 必填。未配置时直接回退本地生成器                                                                    |
| `DEEPSEEK_MODEL`    | `deepseek-flash`           | 以 `GET /models` 的返回为准；同账号下还有 `deepseek-v4-pro`。官方文档写的 `deepseek-v4-flash` 与实际模型名不一致 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口                                                                         |
| `DEEPSEEK_THINKING` | `disabled`                 | **必须保持关闭**：开启思考后推理内容会占满输出额度，正文会变成空字符串                                               |
| `DEEPSEEK_TIMEOUT`  | `60`                       | 单次请求超时秒数                                                                            |
| `DEEPSEEK_PROXY`    | 空                          | 需要走代理时设置；否则依次尝试系统代理和直连                                                              |

实现要点：

- `deepseek_agent.py` 只用标准库 `urllib`，不引入新依赖。
- 模型输出必须经过 `normalize_spec()` 归一化：非法字段类型、重复 key、缺选项的 `select`、越界引用都会被修正或丢弃，保证前端渲染器不会收到畸形数据。
- 存库时写的是**混合形状**（顶层 `fields` + 嵌套 `app`/`view`）。顶层 `fields` 是必需的，因为 `validate_record()` 只从顶层读取字段定义，改为纯嵌套会让必填与类型校验静默失效。
- 调用模型期间不持有 SQLite 写锁（先短事务读规格，网络返回后再开事务写入）。

排查配置是否生效：

```bash
curl -s http://localhost:8000/api/health   # 看 llm.configured 与 llm.model
```

`generate` 的响应会额外带 `engine`（`deepseek` 或 `local`）和 `fallback_reason` 字段。

## API

- `GET /api/health`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}`
- `POST /api/projects/{project_id}/generate`
- `GET /api/projects/{project_id}/versions`
- `POST /api/projects/{project_id}/versions/{version_id}/restore`
- `POST /api/projects/{project_id}/publish`
- `GET /api/public/{slug}`
- `GET|POST /api/projects/{project_id}/records`
- `PATCH|DELETE /api/projects/{project_id}/records/{record_id}`

首次初始化会创建“客户线索管理器”示例项目、v1、两条消息及三条业务记录。未配置 DeepSeek 时生成器为确定性的本地规则实现。
