"""用 DeepSeek 把自然语言需求转换成受控 AppSpec。

设计要点：

1. 只依赖 Python 标准库（urllib），不引入任何新依赖，保持本地 Demo 零配置即可启动。
2. 模型输出一律经过 :func:`normalize_spec` 归一化。越界结构会被修正或丢弃，
   保证前端渲染器和后端 ``validate_record()`` 都不会拿到畸形数据。
3. 任何失败都抛 :class:`LLMError`，由调用方回退到本地规则生成器，
   所以即使没有 API Key 或网络不通，应用依然可用。
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
# 以 GET /models 的实际返回为准：该账号下可用的是 deepseek-flash 与 deepseek-v4-pro。
# 注意官方文档里写的 deepseek-v4-flash 与这里的 deepseek-flash 并不一致，
# 而 deepseek-chat / deepseek-reasoner 已于 2026/07/24 废弃。
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_TIMEOUT = 60.0
DEFAULT_ACCENT = "#087f78"

FIELD_TYPES = ("text", "textarea", "number", "date", "select", "boolean")
SAFE_COLORS = ("green", "red", "amber", "blue", "gray")
RESERVED_KEYS = {"id", "created_at", "updated_at", "project_id"}

MAX_FIELDS = 14
MAX_VISIBLE_FIELDS = 8

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# 只有纯 ASCII 的字段名才适合用来派生 key。
_ASCII_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]*$")


class LLMError(RuntimeError):
    """DeepSeek 调用或输出解析失败。调用方应回退到本地规则生成器。"""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------------------
# 环境配置
# --------------------------------------------------------------------------------------


def load_env_file(path: Optional[str] = None) -> None:
    """把 ``backend/.env`` 里的键值对注入 ``os.environ``，已存在的环境变量不覆盖。

    自行实现是为了不引入 python-dotenv 依赖。
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as error:  # pragma: no cover - 本地文件异常
        LOGGER.warning("读取 %s 失败：%s", path, error)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


class LLMConfig:
    """一次调用所需的全部配置，每次调用时从环境变量重新读取。"""

    def __init__(self) -> None:
        self.api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        self.base_url = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        self.model = (os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip()
        self.timeout = _float_env("DEEPSEEK_TIMEOUT", DEFAULT_TIMEOUT)
        self.thinking = (os.environ.get("DEEPSEEK_THINKING") or "disabled").strip().lower()
        self.proxy = (os.environ.get("DEEPSEEK_PROXY") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> Dict[str, Any]:
        """给 /api/health 用的状态描述，不含 Key 本体。"""
        return {
            "provider": "deepseek",
            "configured": self.configured,
            "model": self.model,
            "base_url": self.base_url,
            "thinking": self.thinking,
            "api_key_hint": ("%s...%s" % (self.api_key[:6], self.api_key[-4:])) if len(self.api_key) > 12 else ("已配置" if self.api_key else ""),
        }


def get_config() -> LLMConfig:
    return LLMConfig()


# --------------------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------------------

SYSTEM_PROMPT = """你是 PromptForge 的 AppSpec 生成器。用户会用中文描述一个业务工具，你要把它转换成一份严格的 JSON 规格。

只输出 JSON 对象本身，不要输出解释文字，不要包 ```json 代码块。

输出结构如下（键名必须完全一致，不要增删顶层键）：

{
  "requirement": "一句话概括你理解到的需求，20 字以内",
  "app": {
    "name": "应用名，10 字以内",
    "description": "一句话副标题，24 字以内",
    "primaryColor": "主题色，必须是 # 开头的十六进制颜色，例如 #087f78、#c2410c、#1d4ed8"
  },
  "entity": {
    "name": "单条记录的名称，2 到 4 个字，例如 设备、工单、客户",
    "namePlural": "列表标题，例如 设备清单、工单列表",
    "fields": [ 字段定义，4 到 10 个 ]
  },
  "features": {
    "create": true,
    "edit": true,
    "delete": true,
    "search": 布尔值,
    "filterField": "用于下拉筛选的字段 key，没有合适的就填 null"
  },
  "view": {
    "layout": "table 或 cards",
    "titleField": "作为主标题的字段 key",
    "visibleFields": ["列表里要展示的字段 key，3 到 6 个"],
    "colorRule": null
  }
}

单个字段定义的结构：

{
  "key": "字段英文标识",
  "label": "中文字段名",
  "type": "text | textarea | number | date | select | boolean",
  "required": 布尔值,
  "options": ["仅 type=select 需要，2 到 8 个选项"]
}

硬性规则，必须全部满足：

1. key 只能由小写英文字母、数字和下划线组成，不能以数字开头，全表内必须唯一。
2. type 是 select 的字段必须给出 options（2 到 8 个不重复的短选项）；其他 type 一律不要出现 options 键。
3. 字段要紧密贴合用户描述的业务，用户提到的信息要逐个落成字段，并直接沿用用户使用的名称作为 label。
4. titleField 必须是某个字段的 key；visibleFields 里每个值也必须是字段 key，按重要性排序取 3 到 6 个。
5. features.filterField 必须是某个 type=select 字段的 key。完全找不到合适的 select 字段时才填 null。
6. 金额、价格、数量、人数、评分这一类用 number；状态、阶段、优先级、类型、分类这一类用 select；时间日期用 date；是/否用 boolean；长段说明用 textarea。
7. 主标题、姓名、编号这类核心文本用 text，并把 required 设为 true；其余字段除非用户强调必填，否则 required 都填 false。
8. colorRule 只在用户明确要求「给某个状态标色 / 高亮」时才给值，结构为
   {"field": "select 字段的 key", "operator": "equals", "value": "该字段的某个 option 值", "color": "green"}
   否则必须填 null。
9. layout 取 table；只有用户明确说要卡片、看板或者图片流时才用 cards。
10. 不要在 JSON 里写注释，不要在 JSON 之外写任何内容。"""


def build_user_message(prompt: str, current_spec: Optional[Dict[str, Any]]) -> str:
    if current_spec is None:
        return "用户的初始需求：\n%s\n\n请据此生成完整的 AppSpec。" % prompt

    existing = json.dumps(current_spec, ensure_ascii=False, separators=(",", ":"))
    return (
        "当前已有的 AppSpec：\n%s\n\n"
        "用户的新要求：\n%s\n\n"
        "请在已有 AppSpec 基础上做增量修改：保留用户没有要求改动的字段（尤其是 key，"
        "改了 key 会导致历史数据对不上），只增删改用户要求的部分；"
        "如果新要求与现有业务方向完全不同，才整体重建。"
        "最终仍然要输出完整、合法的 AppSpec JSON。" % (existing, prompt)
    )


# --------------------------------------------------------------------------------------
# HTTP 调用
# --------------------------------------------------------------------------------------


def _build_openers(config: LLMConfig) -> List[urllib.request.OpenerDirector]:
    """按优先级返回 opener 列表：显式代理 -> 环境代理 -> 直连。

    本机若设置了失效的 HTTP_PROXY，第一次尝试会失败，随后自动降级到直连。
    """
    chain: List[urllib.request.OpenerDirector] = []
    if config.proxy:
        handler = urllib.request.ProxyHandler({"http": config.proxy, "https": config.proxy})
        chain.append(urllib.request.build_opener(handler))
    if urllib.request.getproxies():
        chain.append(urllib.request.build_opener())
    chain.append(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    return chain


def _read_http_error(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", "replace")
    except Exception:  # pragma: no cover - 读取响应体失败
        return error.reason or "无响应内容"
    try:
        payload = json.loads(body)
        detail = payload.get("error")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
        if detail:
            return str(detail)
    except ValueError:
        pass
    return body[:300]


def _post_chat(body: Dict[str, Any], config: LLMConfig) -> Dict[str, Any]:
    url = config.base_url + "/chat/completions"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer %s" % config.api_key,
    }

    connection_errors: List[str] = []
    for opener in _build_openers(config):
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with opener.open(request, timeout=config.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            # 4xx/5xx 是请求或服务端本身的问题，换网络路径没有意义。
            raise LLMError("DeepSeek 返回 HTTP %s：%s" % (error.code, _read_http_error(error)), status=error.code)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            connection_errors.append(str(reason))

    raise LLMError(
        "无法连接 DeepSeek（已尝试 %d 条网络路径）：%s"
        % (len(connection_errors), "; ".join(connection_errors[:3]))
    )


def _call_chat(body: Dict[str, Any], config: LLMConfig) -> Dict[str, Any]:
    try:
        return _post_chat(body, config)
    except LLMError as error:
        # 若某个版本的模型不接受 thinking 参数，剔除后重试一次。
        if error.status == 400 and "thinking" in body:
            LOGGER.warning("DeepSeek 拒绝 thinking 参数，去掉后重试")
            retry_body = dict(body)
            retry_body.pop("thinking", None)
            return _post_chat(retry_body, config)
        raise


def _extract_content(completion: Dict[str, Any]) -> str:
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("DeepSeek 没有返回任何候选结果")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    finish_reason = choice.get("finish_reason")
    message = choice.get("message") or {}
    content = message.get("content")

    if not isinstance(content, str) or not content.strip():
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            # 思考模式开启时，推理内容会先占满 max_tokens，正文就空了。
            raise LLMError(
                "DeepSeek 只返回了思考内容而没有正文（finish_reason=%s）。"
                "通常是因为思考模式占满了输出额度，请将 DEEPSEEK_THINKING 设为 disabled。" % finish_reason
            )
        raise LLMError("DeepSeek 返回的内容为空（finish_reason=%s）" % finish_reason)

    if finish_reason == "length":
        raise LLMError("DeepSeek 输出被 max_tokens 截断（finish_reason=length），AppSpec 不完整")

    return content


def parse_json_content(content: str) -> Dict[str, Any]:
    """容忍 ```json 代码块和前后多余文字，提取第一个完整 JSON 对象。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("DeepSeek 返回的内容里找不到 JSON 对象")
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except ValueError as error:
        raise LLMError("DeepSeek 返回的 JSON 无法解析：%s" % error) from error
    if not isinstance(parsed, dict):
        raise LLMError("DeepSeek 返回的 JSON 根节点不是对象")
    return parsed


# --------------------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------------------


def _clean_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _snake_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if text and text[0].isdigit():
        text = "f_" + text
    return text[:40]


def _normalize_options(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    options: List[str] = []
    for item in value:
        if isinstance(item, (dict, list)):
            continue
        label = _clean_text(item, 20)
        if label and label not in options:
            options.append(label)
        if len(options) >= 8:
            break
    return options


def _normalize_fields(source: Any) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """归一化字段列表，同时返回「模型原始 key -> 合法 key」的映射。"""
    if not isinstance(source, list):
        return [], {}

    fields: List[Dict[str, Any]] = []
    key_map: Dict[str, str] = {}
    used = set()

    for item in source:
        if not isinstance(item, dict):
            continue
        original = _clean_text(item.get("key"), 60)
        label = _clean_text(item.get("label"), 24)
        key = _snake_key(original)
        if not key:
            # 模型偶尔会把中文字段名当 key 用。只有纯 ASCII 的字段名才适合派生 key，
            # 否则「没有 key 只在标签里」这种名字会派生出一个无意义的 "key"。
            if label and _ASCII_LABEL_RE.match(label):
                key = _snake_key(label)
        if not key or key in used or key in RESERVED_KEYS:
            # 生成一个一定不冲突的兜底 key，绝不因为重名而丢掉字段。
            index = len(fields) + 1
            key = "field_%d" % index
            while key in used:
                index += 1
                key = "field_%d" % index

        label = label or key
        field_type = _clean_text(item.get("type"), 20).lower()
        if field_type not in FIELD_TYPES:
            field_type = "text"

        options = _normalize_options(item.get("options"))
        if field_type == "select":
            if len(options) < 2:
                # select 没有足够选项会渲染成空下拉框，退化成文本更安全。
                field_type = "text"
                options = []
        else:
            options = []

        entry: Dict[str, Any] = {
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required")),
        }
        if field_type == "select":
            entry["options"] = options

        used.add(key)
        fields.append(entry)
        if original:
            key_map[original] = key
        if len(fields) >= MAX_FIELDS:
            break

    return fields, key_map


def _resolve_key(value: Any, key_map: Dict[str, str], valid: set) -> str:
    text = _clean_text(value, 60)
    if not text:
        return ""
    candidate = key_map.get(text, _snake_key(text))
    return candidate if candidate in valid else ""


def _normalize_color(value: Any) -> str:
    text = _clean_text(value, 16)
    if _HEX_COLOR_RE.match(text):
        if len(text) == 4:
            text = "#" + "".join(char * 2 for char in text[1:])
        return text.lower()
    return DEFAULT_ACCENT


def _normalize_color_rule(raw: Any, key_map: Dict[str, str], fields: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    definitions = {item["key"]: item for item in fields}
    field_key = _resolve_key(raw.get("field"), key_map, set(definitions))
    if not field_key:
        return None
    definition = definitions[field_key]

    value = raw.get("value")
    if isinstance(value, (dict, list)) or value is None:
        return None
    if definition["type"] == "select":
        # 前端只做相等比较，取值必须落在 options 里，否则高亮永远不会命中。
        if value not in definition.get("options", []):
            return None
    elif isinstance(value, float) and value.is_integer():
        value = int(value)

    color = _clean_text(raw.get("color"), 12).lower()
    if color not in SAFE_COLORS:
        color = "green"
    return {"field": field_key, "operator": "equals", "value": value, "color": color}


def normalize_spec(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把模型输出整理成规范的嵌套 AppSpec。结构不合法时抛 LLMError。"""
    if not isinstance(raw, dict):
        raise LLMError("AppSpec 根节点不是对象")

    app_raw = raw.get("app") if isinstance(raw.get("app"), dict) else {}
    entity_raw = raw.get("entity") if isinstance(raw.get("entity"), dict) else {}
    features_raw = raw.get("features") if isinstance(raw.get("features"), dict) else {}
    view_raw = raw.get("view") if isinstance(raw.get("view"), dict) else {}

    fields, key_map = _normalize_fields(entity_raw.get("fields") or raw.get("fields"))
    if not fields:
        raise LLMError("AppSpec 里没有任何可用字段")
    valid_keys = {item["key"] for item in fields}

    entity_name = _clean_text(entity_raw.get("name") or raw.get("entityName"), 12) or "记录"
    entity_plural = _clean_text(entity_raw.get("namePlural"), 24) or (entity_name + "列表")

    title_field = _resolve_key(view_raw.get("titleField"), key_map, valid_keys) or fields[0]["key"]

    visible_source = view_raw.get("visibleFields")
    visible: List[str] = []
    if isinstance(visible_source, list):
        for item in visible_source:
            key = _resolve_key(item, key_map, valid_keys)
            if key and key not in visible:
                visible.append(key)
            if len(visible) >= MAX_VISIBLE_FIELDS:
                break
    if title_field not in visible:
        visible.insert(0, title_field)
    visible = visible[:MAX_VISIBLE_FIELDS]

    layout = _clean_text(view_raw.get("layout"), 10).lower()
    if layout not in ("table", "cards"):
        layout = "table"

    filter_field = _resolve_key(features_raw.get("filterField"), key_map, valid_keys)
    if filter_field and any(item["key"] == filter_field and item["type"] == "select" for item in fields):
        pass
    else:
        # 没有指定或指定得不合法时，退让到第一个下拉字段，保证筛选能力可用。
        filter_field = next((item["key"] for item in fields if item["type"] == "select"), "")

    color_rule = _normalize_color_rule(view_raw.get("colorRule") or raw.get("colorRule"), key_map, fields)

    return {
        "app": {
            "name": _clean_text(app_raw.get("name") or raw.get("title"), 24) or "业务信息管理器",
            "description": _clean_text(app_raw.get("description") or raw.get("description"), 60),
            "primaryColor": _normalize_color(app_raw.get("primaryColor")),
        },
        "entity": {"name": entity_name, "namePlural": entity_plural, "fields": fields},
        "features": {
            "create": bool(features_raw.get("create", True)),
            "edit": bool(features_raw.get("edit", True)),
            "delete": bool(features_raw.get("delete", True)),
            "search": bool(features_raw.get("search", True)),
            "filterField": filter_field or None,
        },
        "view": {
            "layout": layout,
            "titleField": title_field,
            "visibleFields": visible,
            "colorRule": color_rule,
        },
    }


def to_storage_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """把规范 AppSpec 转成存库用的形状。

    必须保留顶层 ``fields``：``main.py`` 的 ``validate_record()`` 只从顶层读字段定义，
    换成纯嵌套结构会让必填和类型校验静默失效。
    同时补上 ``app`` / ``view`` / ``entity.namePlural``，这些只有嵌套形状才会被前端读取。
    """
    stored: Dict[str, Any] = {
        "title": spec["app"]["name"],
        "description": spec["app"]["description"],
        "entityName": spec["entity"]["name"],
        "layout": spec["view"]["layout"],
        "fields": spec["entity"]["fields"],
        "app": spec["app"],
        "entity": {"namePlural": spec["entity"]["namePlural"]},
        "features": spec["features"],
        "view": spec["view"],
    }
    if spec["view"].get("colorRule"):
        stored["colorRule"] = spec["view"]["colorRule"]
    return stored


# --------------------------------------------------------------------------------------
# 变更摘要（本地计算，不再额外调用模型）
# --------------------------------------------------------------------------------------


def read_spec_fields(spec: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """兼容平面与嵌套两种存放形状地读取字段列表。"""
    if not isinstance(spec, dict):
        return []
    entity = spec.get("entity")
    if isinstance(entity, dict) and isinstance(entity.get("fields"), list):
        return [item for item in entity["fields"] if isinstance(item, dict)]
    fields = spec.get("fields")
    return [item for item in fields if isinstance(item, dict)] if isinstance(fields, list) else []


def read_spec_layout(spec: Optional[Dict[str, Any]]) -> str:
    if not isinstance(spec, dict):
        return ""
    view = spec.get("view")
    if isinstance(view, dict) and view.get("layout"):
        return str(view["layout"])
    return str(spec.get("layout") or "")


def read_spec_features(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        return {}
    features = spec.get("features")
    return features if isinstance(features, dict) else {}


def summarize_changes(old_spec: Optional[Dict[str, Any]], new_spec: Dict[str, Any]) -> str:
    parts: List[str] = []

    old_fields = [item for item in read_spec_fields(old_spec) if item.get("key")]
    old_by_key = {item["key"]: item for item in old_fields}
    new_fields = new_spec["entity"]["fields"]
    new_by_key = {item["key"]: item for item in new_fields}

    added = [item for key, item in new_by_key.items() if key not in old_by_key]
    removed = [key for key in old_by_key if key not in new_by_key]
    if added:
        labels = "、".join(item.get("label") or item["key"] for item in added[:6])
        if len(added) > 6:
            labels += " 等 %d 个" % len(added)
        parts.append("新增字段：%s" % labels)
    if removed:
        parts.append("移除字段 %d 个" % len(removed))

    changed = [
        new_by_key[key]
        for key in new_by_key
        if key in old_by_key
        and (
            old_by_key[key].get("type") != new_by_key[key].get("type")
            or old_by_key[key].get("label") != new_by_key[key].get("label")
            or old_by_key[key].get("options") != new_by_key[key].get("options")
        )
    ]
    if changed:
        parts.append("调整字段：%s" % "、".join(item.get("label") or item["key"] for item in changed[:4]))

    old_layout = read_spec_layout(old_spec)
    if old_layout and old_layout != new_spec["view"]["layout"]:
        parts.append("切换为%s布局" % ("卡片" if new_spec["view"]["layout"] == "cards" else "表格"))

    old_features = read_spec_features(old_spec)
    if old_features:
        if bool(old_features.get("search")) != new_spec["features"]["search"]:
            parts.append("开启搜索" if new_spec["features"]["search"] else "关闭搜索")
        old_filter = old_features.get("filterField") or old_features.get("filter")
        new_filter = new_spec["features"]["filterField"]
        if bool(old_filter) != bool(new_filter):
            parts.append("开启筛选" if new_filter else "关闭筛选")
    if new_spec["view"]["colorRule"]:
        parts.append("设置状态高亮")

    if not parts:
        parts.append("校验并规范化字段与视图配置")
    return "；".join(parts)


def build_steps(
    new_spec: Dict[str, Any],
    old_spec: Optional[Dict[str, Any]],
    requirement: str,
) -> List[Dict[str, str]]:
    understanding = requirement or ("按需求生成 %s" % new_spec["app"]["name"])
    return [
        {"agent": "team_lead", "status": "completed", "summary": "解析需求：%s" % understanding},
        {
            "agent": "engineer",
            "status": "completed",
            "summary": "DeepSeek 生成 AppSpec 并归一化，共 %d 个字段" % len(new_spec["entity"]["fields"]),
        },
        {"agent": "engineer", "status": "completed", "summary": summarize_changes(old_spec, new_spec)},
    ]


# --------------------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------------------


def generate_spec(prompt: str, current_spec: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, str]], str]:
    """调用 DeepSeek 生成 AppSpec。

    返回 ``(存库形状的 spec, steps, 需求理解)``。失败时抛 :class:`LLMError`。
    """
    config = get_config()
    if not config.configured:
        raise LLMError("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek")

    body: Dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(prompt, current_spec)},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": False,
        # JSON 模式要求提示词里出现 json 字样，SYSTEM_PROMPT 已满足。
        "response_format": {"type": "json_object"},
    }
    if config.thinking in ("disabled", "enabled"):
        body["thinking"] = {"type": config.thinking}

    completion = _call_chat(body, config)
    LOGGER.info("DeepSeek 调用完成：model=%s usage=%s", config.model, completion.get("usage"))

    raw = parse_json_content(_extract_content(completion))
    spec = normalize_spec(raw)
    requirement = _clean_text(raw.get("requirement"), 40)
    steps = build_steps(spec, current_spec, requirement)

    return to_storage_spec(spec), steps, requirement
