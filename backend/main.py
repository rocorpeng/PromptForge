import copy
import json
import logging
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import Body, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr

import deepseek_agent
from deepseek_agent import LLMError

LOGGER = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "promptforge.db")

# 读取 backend/.env，把 DEEPSEEK_* 配置注入环境变量（不覆盖已存在的变量）。
deepseek_agent.load_env_file()


class ProjectCreate(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=120)
    description: Optional[constr(strip_whitespace=True, max_length=1000)] = None


class GenerateRequest(BaseModel):
    prompt: constr(strip_whitespace=True, min_length=1, max_length=5000)


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="microseconds") + "Z"


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH, timeout=15.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def field(
    key: str,
    label: str,
    field_type: str,
    required: bool = False,
    options: Optional[List[str]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "key": key,
        "label": label,
        "type": field_type,
        "required": required,
    }
    if options is not None:
        result["options"] = options
    return result


def base_spec(kind: str) -> Dict[str, Any]:
    common_features = {
        "create": True,
        "edit": True,
        "delete": True,
        "search": False,
        "filter": False,
    }
    if kind == "customer_lead":
        return {
            "title": "客户线索管理器",
            "description": "集中管理客户线索和跟进状态。",
            "entityName": "客户线索",
            "layout": "table",
            "features": common_features,
            "fields": [
                field("name", "客户姓名", "text", True),
                field("company", "公司", "text"),
                field("phone", "联系电话", "text"),
                field("email", "邮箱", "text"),
                field("status", "跟进状态", "select", True, ["新线索", "跟进中", "已转化", "已关闭"]),
                field("source", "线索来源", "select", False, ["官网", "活动", "转介绍", "其他"]),
                field("estimated_value", "预计金额", "number"),
                field("follow_up_date", "下次跟进日期", "date"),
                field("notes", "备注", "textarea"),
            ],
        }
    if kind == "task":
        return {
            "title": "任务管理器",
            "description": "创建、分配并跟踪团队任务。",
            "entityName": "任务",
            "layout": "table",
            "features": common_features,
            "fields": [
                field("title", "任务标题", "text", True),
                field("description", "任务描述", "textarea"),
                field("priority", "优先级", "select", True, ["低", "中", "高", "紧急"]),
                field("status", "状态", "select", True, ["待处理", "进行中", "已完成"]),
                field("assignee", "负责人", "text"),
                field("due_date", "截止日期", "date"),
                field("completed", "是否完成", "boolean"),
            ],
        }
    if kind == "feedback":
        return {
            "title": "用户反馈管理器",
            "description": "收集、分类并处理用户反馈。",
            "entityName": "反馈",
            "layout": "table",
            "features": common_features,
            "fields": [
                field("title", "反馈标题", "text", True),
                field("content", "反馈内容", "textarea", True),
                field("contact", "联系方式", "text"),
                field("category", "反馈类型", "select", False, ["建议", "问题", "投诉", "表扬"]),
                field("rating", "满意度", "number"),
                field("submitted_at", "提交日期", "date"),
                field("handled", "是否处理", "boolean"),
            ],
        }
    if kind == "event_registration":
        return {
            "title": "活动报名管理器",
            "description": "登记活动参与者并跟踪签到状态。",
            "entityName": "报名记录",
            "layout": "table",
            "features": common_features,
            "fields": [
                field("attendee_name", "报名人", "text", True),
                field("phone", "联系电话", "text", True),
                field("email", "邮箱", "text"),
                field("event_name", "活动名称", "text", True),
                field("participants", "参与人数", "number"),
                field("registration_date", "报名日期", "date"),
                field("checked_in", "是否签到", "boolean"),
                field("notes", "备注", "textarea"),
            ],
        }
    return {
        "title": "业务信息管理器",
        "description": "根据需求管理结构化业务信息。",
        "entityName": "业务记录",
        "layout": "table",
        "features": common_features,
        "fields": [
            field("title", "标题", "text", True),
            field("description", "描述", "textarea"),
            field("amount", "数值", "number"),
            field("date", "日期", "date"),
            field("category", "分类", "select", False, ["默认", "其他"]),
            field("active", "是否启用", "boolean"),
        ],
    }


def detect_kind(prompt: str) -> Optional[str]:
    normalized = prompt.lower()
    if any(word in normalized for word in ["客户", "线索", "crm", "销售机会"]):
        return "customer_lead"
    if any(word in normalized for word in ["活动报名", "报名", "参会", "签到"]):
        return "event_registration"
    if any(word in normalized for word in ["反馈", "意见", "投诉", "满意度"]):
        return "feedback"
    if any(word in normalized for word in ["任务", "待办", "todo", "工单"]):
        return "task"
    return None


def add_field_once(spec: Dict[str, Any], new_field: Dict[str, Any]) -> bool:
    fields = spec.setdefault("fields", [])
    if any(item.get("key") == new_field["key"] for item in fields):
        return False
    fields.append(new_field)
    return True


def build_spec(prompt: str, current_spec: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    kind = detect_kind(prompt)
    if kind is not None:
        spec = base_spec(kind)
        action = "根据业务类型生成完整 AppSpec"
    elif current_spec is not None:
        spec = copy.deepcopy(current_spec)
        action = "在当前 AppSpec 上应用增量修改"
    else:
        spec = base_spec("generic")
        action = "生成通用 AppSpec"

    changes: List[str] = []
    normalized = prompt.lower()
    if "优先级" in normalized:
        if add_field_once(spec, field("priority", "优先级", "select", False, ["低", "中", "高", "紧急"])):
            changes.append("增加优先级字段")
    if "卡片" in normalized or "cards" in normalized or "card" in normalized:
        spec["layout"] = "cards"
        changes.append("切换为卡片布局")
    elif "表格" in normalized or "table" in normalized:
        spec["layout"] = "table"
        changes.append("切换为表格布局")
    features = spec.setdefault("features", {})
    for operation in ["create", "edit", "delete", "search", "filter"]:
        features.setdefault(operation, operation in ["create", "edit", "delete"])
    if "搜索" in normalized or "search" in normalized:
        features["search"] = True
        changes.append("启用搜索")
    if "筛选" in normalized or "过滤" in normalized or "filter" in normalized:
        features["filter"] = True
        changes.append("启用筛选")
    if "绿色" in normalized or "green" in normalized:
        status_field = next((item for item in spec.get("fields", []) if item.get("key") == "status"), None)
        color_value = "已完成"
        if status_field and status_field.get("options"):
            color_value = status_field["options"][-1]
        spec["colorRule"] = {
            "field": "status" if status_field else spec["fields"][0]["key"],
            "operator": "equals",
            "value": color_value,
            "color": "green",
        }
        changes.append("增加绿色条件样式")

    steps = [
        {"agent": "team_lead", "status": "completed", "summary": "识别需求并拆分数据、布局和操作能力"},
        {"agent": "engineer", "status": "completed", "summary": action},
        {"agent": "engineer", "status": "completed", "summary": "；".join(changes) if changes else "校验字段 key 和 AppSpec 结构"},
    ]
    return spec, steps


def generate_app_spec(
    prompt: str,
    current_spec: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, str]], str, Optional[str]]:
    """优先调用 DeepSeek 生成 AppSpec，失败时回退到本地规则生成器。

    返回 ``(spec, steps, engine, fallback_reason)``，engine 取值 ``deepseek`` 或 ``local``。
    回退保证在没有 API Key、网络不通或模型返回异常时应用依然可用。
    """
    if not deepseek_agent.get_config().configured:
        spec, steps = build_spec(prompt, current_spec)
        return spec, steps, "local", "未配置 DEEPSEEK_API_KEY"

    try:
        spec, steps, _requirement = deepseek_agent.generate_spec(prompt, current_spec)
        return spec, steps, "deepseek", None
    except LLMError as error:
        LOGGER.warning("DeepSeek 生成失败，回退本地规则生成器：%s", error)
        spec, steps = build_spec(prompt, current_spec)
        return spec, steps, "local", str(error)


def describe_generation(spec: Dict[str, Any], engine: str, fallback_reason: Optional[str]) -> str:
    """生成写入对话流的工程师消息。"""
    title = spec.get("title") or (spec.get("app") or {}).get("name") or "未命名应用"
    field_count = len(deepseek_agent.read_spec_fields(spec))
    if engine == "deepseek":
        return "已由 DeepSeek 生成 AppSpec：%s，共 %d 个字段。" % (title, field_count)
    return "DeepSeek 不可用（%s），已回退本地规则生成 AppSpec：%s，共 %d 个字段。" % (
        fallback_reason or "未知原因",
        title,
        field_count,
    )


def init_database() -> None:
    with database() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                slug TEXT UNIQUE,
                published_version_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (published_version_id) REFERENCES versions(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'team_lead', 'engineer')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                app_spec TEXT NOT NULL,
                source_prompt TEXT,
                restored_from_version_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (restored_from_version_id) REFERENCES versions(id),
                UNIQUE (project_id, version_number)
            );
            CREATE TABLE IF NOT EXISTS generation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                steps TEXT NOT NULL,
                version_id INTEGER,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (version_id) REFERENCES versions(id)
            );
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project_id, id);
            CREATE INDEX IF NOT EXISTS idx_versions_project ON versions(project_id, version_number);
            CREATE INDEX IF NOT EXISTS idx_records_project ON records(project_id, id);
            """
        )
        message_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "updated_at" not in message_columns:
            connection.execute("ALTER TABLE messages ADD COLUMN updated_at TEXT")
            connection.execute("UPDATE messages SET updated_at = created_at WHERE updated_at IS NULL")
        version_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(versions)").fetchall()
        }
        if "updated_at" not in version_columns:
            connection.execute("ALTER TABLE versions ADD COLUMN updated_at TEXT")
            connection.execute("UPDATE versions SET updated_at = created_at WHERE updated_at IS NULL")
        existing = connection.execute(
            "SELECT id FROM projects WHERE name = ? ORDER BY id LIMIT 1",
            ("客户线索管理器",),
        ).fetchone()
        if existing is None:
            now = utc_now()
            cursor = connection.execute(
                "INSERT INTO projects(name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("客户线索管理器", "用于管理销售线索、跟进状态和预计金额。", now, now),
            )
            project_id = int(cursor.lastrowid)
            spec = base_spec("customer_lead")
            connection.execute(
                "INSERT INTO versions(project_id, version_number, app_spec, source_prompt, created_at, updated_at) VALUES (?, 1, ?, ?, ?, ?)",
                (project_id, json_dump(spec), "创建一个客户线索管理器", now, now),
            )
            connection.executemany(
                "INSERT INTO messages(project_id, role, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (project_id, "user", "创建一个客户线索管理器", now, now),
                    (project_id, "engineer", "已生成客户信息、跟进状态、来源和日期字段，并启用增删改能力。", now, now),
                ],
            )
            seed_records = [
                {"name": "张伟", "company": "星河科技", "phone": "13800000001", "email": "zhangwei@example.com", "status": "新线索", "source": "官网", "estimated_value": 50000, "follow_up_date": "2026-09-22", "notes": "关注团队版方案"},
                {"name": "李娜", "company": "远山设计", "phone": "13800000002", "email": "lina@example.com", "status": "跟进中", "source": "活动", "estimated_value": 80000, "follow_up_date": "2026-09-25", "notes": "已安排产品演示"},
                {"name": "王强", "company": "海风零售", "phone": "13800000003", "email": "wangqiang@example.com", "status": "已转化", "source": "转介绍", "estimated_value": 120000, "follow_up_date": "2026-09-30", "notes": "准备签约材料"},
            ]
            connection.executemany(
                "INSERT INTO records(project_id, data, created_at, updated_at) VALUES (?, ?, ?, ?)",
                [(project_id, json_dump(item), now, now) for item in seed_records],
            )
        connection.commit()


def project_or_404(connection: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="project not found")
    return row


def project_json(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "slug": row["slug"],
        "published_version_id": row["published_version_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def message_json(row: sqlite3.Row) -> Dict[str, Any]:
    return {"id": row["id"], "project_id": row["project_id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def version_json(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "version_number": row["version_number"],
        "app_spec": json.loads(row["app_spec"]),
        "source_prompt": row["source_prompt"],
        "restored_from_version_id": row["restored_from_version_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def record_json(row: sqlite3.Row) -> Dict[str, Any]:
    result = {"id": row["id"], "project_id": row["project_id"], "created_at": row["created_at"], "updated_at": row["updated_at"]}
    result["data"] = json.loads(row["data"])
    return result


def latest_version(connection: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM versions WHERE project_id = ? ORDER BY version_number DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def create_version(
    connection: sqlite3.Connection,
    project_id: int,
    spec: Dict[str, Any],
    source_prompt: str,
    restored_from: Optional[int] = None,
) -> sqlite3.Row:
    next_number = connection.execute(
        "SELECT COALESCE(MAX(version_number), 0) + 1 FROM versions WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    now = utc_now()
    cursor = connection.execute(
        "INSERT INTO versions(project_id, version_number, app_spec, source_prompt, restored_from_version_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, next_number, json_dump(spec), source_prompt, restored_from, now, now),
    )
    connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
    return connection.execute("SELECT * FROM versions WHERE id = ?", (cursor.lastrowid,)).fetchone()


def require_record_object(payload: Dict[str, Any], allow_empty: bool = False) -> Dict[str, Any]:
    if not isinstance(payload, dict) or (not payload and not allow_empty):
        raise HTTPException(status_code=422, detail="record must be a non-empty JSON object")
    return payload


def validate_record(spec: Dict[str, Any], data: Dict[str, Any], partial: bool = False) -> None:
    definitions = {item["key"]: item for item in spec.get("fields", [])}
    if not partial:
        missing = [item["key"] for item in definitions.values() if item.get("required") and data.get(item["key"]) in (None, "")]
        if missing:
            raise HTTPException(status_code=422, detail="missing required fields: " + ", ".join(missing))
    for key, value in data.items():
        definition = definitions.get(key)
        if definition is None or value is None:
            continue
        field_type = definition.get("type")
        valid = True
        if field_type in ("text", "textarea"):
            valid = isinstance(value, str)
        elif field_type == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif field_type == "boolean":
            valid = isinstance(value, bool)
        elif field_type == "date":
            valid = isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value) is not None
            if valid:
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    valid = False
        elif field_type == "select":
            valid = isinstance(value, str) and value in definition.get("options", [])
        if not valid:
            raise HTTPException(status_code=422, detail="invalid value for field: " + key)


def slug_base(name: str, project_id: int) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized if normalized else "project-%d" % project_id


def register_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health():
        try:
            with database() as connection:
                connection.execute("SELECT 1").fetchone()
            return {
                "status": "ok",
                "database": os.path.basename(DB_PATH),
                "llm": deepseek_agent.get_config().describe(),
            }
        except sqlite3.Error as error:
            LOGGER.exception("Database health check failed")
            raise HTTPException(status_code=503, detail="database unavailable") from error

    @app.get("/api/projects")
    def list_projects():
        with database() as connection:
            rows = connection.execute(
                """SELECT p.*,
                   (SELECT COUNT(*) FROM versions v WHERE v.project_id = p.id) AS version_count,
                   (SELECT COUNT(*) FROM records r WHERE r.project_id = p.id) AS record_count,
                   (SELECT MAX(version_number) FROM versions v WHERE v.project_id = p.id) AS latest_version_number
                   FROM projects p ORDER BY p.updated_at DESC, p.id DESC"""
            ).fetchall()
            projects = []
            for row in rows:
                item = project_json(row)
                item.update({"version_count": row["version_count"], "record_count": row["record_count"], "latest_version_number": row["latest_version_number"]})
                projects.append(item)
            return {"projects": projects}

    @app.post("/api/projects", status_code=status.HTTP_201_CREATED)
    def create_project(payload: ProjectCreate):
        now = utc_now()
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO projects(name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (payload.name, payload.description, now, now),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return {"project": project_json(row)}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int):
        with database() as connection:
            project = project_or_404(connection, project_id)
            messages = connection.execute("SELECT * FROM messages WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
            versions = connection.execute("SELECT * FROM versions WHERE project_id = ? ORDER BY version_number DESC", (project_id,)).fetchall()
            return {
                "project": project_json(project),
                "messages": [message_json(item) for item in messages],
                "versions": [version_json(item) for item in versions],
            }

    @app.post("/api/projects/{project_id}/generate")
    def generate(project_id: int, payload: GenerateRequest):
        # 先在短事务里读出当前规格，避免在等待外部模型响应时一直占着 SQLite 写锁。
        with database() as connection:
            project_or_404(connection, project_id)
            current = latest_version(connection, project_id)
            current_spec = json.loads(current["app_spec"]) if current else None

        spec, steps, engine, fallback_reason = generate_app_spec(payload.prompt, current_spec)

        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project_or_404(connection, project_id)
            now = utc_now()
            run_cursor = connection.execute(
                "INSERT INTO generation_runs(project_id, prompt, steps, status, created_at, updated_at) VALUES (?, ?, ?, 'running', ?, ?)",
                (project_id, payload.prompt, json_dump(steps), now, now),
            )
            lead_content = "已分析需求：%s" % steps[0]["summary"]
            engineer_content = describe_generation(spec, engine, fallback_reason)
            message_values = [
                (project_id, "user", payload.prompt, now, now),
                (project_id, "team_lead", lead_content, now, now),
                (project_id, "engineer", engineer_content, now, now),
            ]
            message_ids = []
            for values in message_values:
                cursor = connection.execute("INSERT INTO messages(project_id, role, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", values)
                message_ids.append(cursor.lastrowid)
            version = create_version(connection, project_id, spec, payload.prompt)
            finished_at = utc_now()
            connection.execute(
                "UPDATE generation_runs SET version_id = ?, status = 'completed', updated_at = ? WHERE id = ?",
                (version["id"], finished_at, run_cursor.lastrowid),
            )
            connection.commit()
            messages = connection.execute(
                "SELECT * FROM messages WHERE id IN (?, ?, ?) ORDER BY id", tuple(message_ids)
            ).fetchall()
            return {
                "run_id": run_cursor.lastrowid,
                "steps": steps,
                "engine": engine,
                "fallback_reason": fallback_reason,
                "messages": [message_json(item) for item in messages],
                "version": version_json(version),
            }

    @app.get("/api/projects/{project_id}/versions")
    def list_versions(project_id: int):
        with database() as connection:
            project_or_404(connection, project_id)
            rows = connection.execute("SELECT * FROM versions WHERE project_id = ? ORDER BY version_number DESC", (project_id,)).fetchall()
            return {"versions": [version_json(item) for item in rows]}

    @app.post("/api/projects/{project_id}/versions/{version_id}/restore", status_code=status.HTTP_201_CREATED)
    def restore_version(project_id: int, version_id: int):
        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project_or_404(connection, project_id)
            source = connection.execute("SELECT * FROM versions WHERE id = ? AND project_id = ?", (version_id, project_id)).fetchone()
            if source is None:
                raise HTTPException(status_code=404, detail="version not found")
            restored = create_version(
                connection,
                project_id,
                json.loads(source["app_spec"]),
                "恢复自版本 v%d" % source["version_number"],
                source["id"],
            )
            connection.commit()
            return {"version": version_json(restored)}

    @app.post("/api/projects/{project_id}/publish")
    def publish(project_id: int):
        with database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project = project_or_404(connection, project_id)
            version = latest_version(connection, project_id)
            if version is None:
                raise HTTPException(status_code=409, detail="project has no version to publish")
            slug = project["slug"]
            if not slug:
                base = slug_base(project["name"], project_id)
                slug = base
                suffix = 2
                while connection.execute("SELECT 1 FROM projects WHERE slug = ? AND id != ?", (slug, project_id)).fetchone():
                    slug = "%s-%d" % (base, suffix)
                    suffix += 1
            now = utc_now()
            connection.execute(
                "UPDATE projects SET slug = ?, published_version_id = ?, updated_at = ? WHERE id = ?",
                (slug, version["id"], now, project_id),
            )
            connection.commit()
            updated = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return {"slug": slug, "public_url": "/api/public/%s" % slug, "project": project_json(updated), "version": version_json(version)}

    @app.get("/api/public/{slug}")
    def public_project(slug: str):
        with database() as connection:
            project = connection.execute("SELECT * FROM projects WHERE slug = ? AND published_version_id IS NOT NULL", (slug,)).fetchone()
            if project is None:
                raise HTTPException(status_code=404, detail="published project not found")
            version = connection.execute("SELECT * FROM versions WHERE id = ? AND project_id = ?", (project["published_version_id"], project["id"])).fetchone()
            if version is None:
                raise HTTPException(status_code=404, detail="published version not found")
            records = connection.execute("SELECT * FROM records WHERE project_id = ? ORDER BY id DESC", (project["id"],)).fetchall()
            return {"project": project_json(project), "version": version_json(version), "app_spec": json.loads(version["app_spec"]), "records": [record_json(item) for item in records]}

    @app.get("/api/projects/{project_id}/records")
    def list_records(project_id: int):
        with database() as connection:
            project_or_404(connection, project_id)
            rows = connection.execute("SELECT * FROM records WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
            return {"records": [record_json(item) for item in rows]}

    @app.post("/api/projects/{project_id}/records", status_code=status.HTTP_201_CREATED)
    def create_record(project_id: int, payload: Dict[str, Any] = Body(...)):
        data = require_record_object(payload)
        with database() as connection:
            project_or_404(connection, project_id)
            version = latest_version(connection, project_id)
            if version is None:
                raise HTTPException(status_code=409, detail="generate an AppSpec before creating records")
            validate_record(json.loads(version["app_spec"]), data)
            now = utc_now()
            cursor = connection.execute(
                "INSERT INTO records(project_id, data, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (project_id, json_dump(data), now, now),
            )
            connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
            connection.commit()
            row = connection.execute("SELECT * FROM records WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return {"record": record_json(row)}

    @app.patch("/api/projects/{project_id}/records/{record_id}")
    def update_record(project_id: int, record_id: int, payload: Dict[str, Any] = Body(...)):
        patch = require_record_object(payload)
        with database() as connection:
            project_or_404(connection, project_id)
            row = connection.execute("SELECT * FROM records WHERE id = ? AND project_id = ?", (record_id, project_id)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="record not found")
            data = json.loads(row["data"])
            data.update(patch)
            version = latest_version(connection, project_id)
            if version is not None:
                validate_record(json.loads(version["app_spec"]), data)
            now = utc_now()
            connection.execute("UPDATE records SET data = ?, updated_at = ? WHERE id = ?", (json_dump(data), now, record_id))
            connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
            connection.commit()
            updated = connection.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
            return {"record": record_json(updated)}

    @app.delete("/api/projects/{project_id}/records/{record_id}")
    def delete_record(project_id: int, record_id: int):
        with database() as connection:
            project_or_404(connection, project_id)
            cursor = connection.execute("DELETE FROM records WHERE id = ? AND project_id = ?", (record_id, project_id))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="record not found")
            now = utc_now()
            connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
            connection.commit()
            return {"deleted": True, "id": record_id}


init_database()

app = FastAPI(
    title="PromptForge Local API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8080",
        "http://localhost:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_routes(app)


# ---------------------------DO NOT EDIT CODE BELOW THIS LINE---------------------------------
# This is the entry point for the FastAPI application.
if __name__ == "__main__":
    port = int(os.environ.get("_BYTEFAAS_RUNTIME_PORT", 8000))
    config = uvicorn.Config("main:app", port=port, log_level="info", host=None)
    server = uvicorn.Server(config)
    server.run()
# --------------------------------------------------------------------------------------------
