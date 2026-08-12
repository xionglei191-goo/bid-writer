from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .database import Database
from .llm import LlmClient
from .utils import content_hash


class KnowledgeRewriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=20)
    summary: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=30)


class RequirementEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: int
    text: str = Field(min_length=1)


class SectionDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=20)
    evidence: list[RequirementEvidence] = Field(default_factory=list)
    confirmations: list[str] = Field(default_factory=list)
    visual_suggestions: list[str] = Field(default_factory=list)


class SilverQueryCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=4, max_length=300)
    query_kind: Literal["direct", "synonym", "tender_clause", "confusing_negative"]
    expected_match: bool


class SilverQueryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[SilverQueryCase] = Field(min_length=4, max_length=16)


class SilverReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=80)
    severity: Literal["low", "medium", "high"]
    message: str = Field(min_length=2, max_length=500)


class SilverCaseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: int = Field(gt=0)
    decision: Literal["pass", "reject", "escalate"]
    confidence: float = Field(ge=0, le=1)
    issues: list[SilverReviewIssue] = Field(default_factory=list, max_length=20)


class SilverReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviews: list[SilverCaseReview] = Field(min_length=1, max_length=100)


KnowledgeUnitType = Literal[
    "construction_method", "quality_control", "safety_measure", "schedule_plan",
    "resource_plan", "organization_chart", "process_flow", "site_layout",
    "table_template", "management_measure",
]


class KnowledgeExtractionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_section_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    unit_type: KnowledgeUnitType
    content: str = Field(min_length=20)
    summary: str = Field(min_length=5, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)
    applicability: str = Field(min_length=2, max_length=500)
    risk_level: Literal["low", "medium", "high"]
    source_quote: str = Field(min_length=8, max_length=1200)

    @field_validator("source_section_id", mode="before")
    @classmethod
    def normalize_source_section_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            match = re.fullmatch(r"\s*SECTION\s*:\s*(\d+)\s*", value, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return value

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk_level(cls, value: Any) -> Any:
        return {"低": "low", "中": "medium", "高": "high", "低风险": "low", "中风险": "medium", "高风险": "high"}.get(str(value).strip(), value)


class KnowledgeExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[KnowledgeExtractionCandidate] = Field(min_length=1, max_length=20)


class KnowledgeReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(default="model_review_issue", min_length=2, max_length=80)
    severity: Literal["low", "medium", "high"]
    message: str = Field(min_length=2, max_length=500, validation_alias=AliasChoices("message", "description"))

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> Any:
        return {"低": "low", "中": "medium", "高": "high", "低风险": "low", "中风险": "medium", "高风险": "high"}.get(str(value).strip(), value)


class KnowledgeCandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(ge=0)
    decision: Literal["pass", "revise", "escalate", "reject"]
    confidence: float = Field(ge=0, le=1)
    issues: list[KnowledgeReviewIssue] = Field(default_factory=list, max_length=20)
    corrected_content: str = Field(default="", max_length=12000)

    @model_validator(mode="before")
    @classmethod
    def normalize_issue_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        severity = normalized.pop("severity", "medium")
        reason = str(normalized.pop("reason", "") or "").strip()
        if normalized.get("confidence") is None:
            normalized["confidence"] = 0
        corrected = normalized.get("corrected_content")
        if isinstance(corrected, dict):
            normalized["corrected_content"] = str(corrected.get("content") or "")
        elif corrected is None:
            normalized["corrected_content"] = ""
        issues = normalized.get("issues")
        if isinstance(issues, list):
            normalized["issues"] = [
                {"code": "model_review_issue", "severity": severity, "message": item}
                if isinstance(item, str)
                else ({**item, "severity": item.get("severity", severity)} if isinstance(item, dict) else item)
                for item in issues
            ]
        elif reason:
            normalized["issues"] = [
                {"code": "model_review_reason", "severity": severity, "message": reason[:500]}
            ]
        elif issues is None:
            normalized["issues"] = []
        if reason and not normalized.get("issues"):
            normalized["issues"] = [
                {"code": "model_review_reason", "severity": severity, "message": reason[:500]}
            ]
        return normalized

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: Any) -> Any:
        return {
            "通过": "pass", "复核通过": "pass", "修改": "revise", "建议修改": "revise",
            "升级": "escalate", "升级复核": "escalate", "驳回": "reject", "拒绝": "reject",
        }.get(str(value).strip(), value)


class KnowledgeReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviews: list[KnowledgeCandidateReview] = Field(min_length=1, max_length=20)


@dataclass(frozen=True)
class PromptSpec:
    key: str
    version: str
    instructions: str
    template: str
    output_model: type[BaseModel]

    @property
    def schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema()

    @property
    def prompt_hash(self) -> str:
        material = json.dumps(
            {
                "key": self.key,
                "version": self.version,
                "instructions": self.instructions,
                "template": self.template,
                "schema": self.schema,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return content_hash(material)

    def render(self, **values: str) -> str:
        return self.template.format(**values)


KNOWLEDGE_REWRITE_PROMPT = PromptSpec(
    key="knowledge.rewrite",
    version="1.0.0",
    instructions="你是建设工程技术标知识工程专家。不得编造参数，不得把示意内容写成现场事实。",
    template=(
        "请将以下历史技术标内容重构为可复用知识。删除具体项目、客户、地域、人员、设备数量和未经来源确认的承诺；"
        "保留可验证的施工逻辑、工艺步骤、质量检查、安全措施和验收逻辑。输出JSON："
        '{{"title":"...","content":"Markdown正文","summary":"...","tags":["..."]}}。\n\n'
        "资料：\n{source_material}"
    ),
    output_model=KnowledgeRewriteOutput,
)

SECTION_DRAFT_PROMPT = PromptSpec(
    key="production.section-draft",
    version="1.0.0",
    instructions="你是建设工程技术标编制专家。正文必须逐条响应要求并保留知识来源，不得复制旧项目事实。",
    template=(
        "请根据项目事实、条款和已审核知识编制技术标章节。不得编造人员数量、设备型号、工程参数和承诺。"
        "缺失参数写入confirmations。evidence.text必须逐字引用content中的支持片段。输出JSON："
        '{{"content":"Markdown正文","evidence":[{{"requirement_id":1,"text":"正文证据原文"}}],'
        '"confirmations":["待确认事项"],"visual_suggestions":["图表建议"]}}。\n\n'
        "项目：{project_name}\n行业：{industry}\n参数：{profile}\n章节：{section_title}\n条款：{requirements}\n\n"
        "已审核知识：\n{source_text}"
    ),
    output_model=SectionDraftOutput,
)

SILVER_QUERY_PROMPT = PromptSpec(
    key="evaluation.silver-query",
    version="1.0.1",
    instructions=(
        "你是建设工程知识检索评测设计专家。问题必须能从给定知识判断，不能引入资料中不存在的项目事实。"
        "困难负样本必须属于相邻专业但不同子主题，给定知识既不能直接回答，也不能通过肯定、否定或一般背景间接回答。"
        "不得把缺少具体数值的问题、给定结论的反向问法或同一措施的细化问题标为负样本。"
    ),
    template=(
        "根据以下已审核并发布的知识生成{count}条检索评测问题。至少包含direct、synonym、tender_clause和"
        "confusing_negative四类。正向问题expected_match为true；混淆负样本为false。"
        "混淆负样本应与正文关键词保持有限重叠，但必须询问正文完全未覆盖的不同专业对象。输出JSON："
        '{{"cases":[{{"query":"...","query_kind":"direct","expected_match":true}}]}}。\n\n'
        "标题：{title}\n行业：{industry}\n知识类型：{unit_type}\n正文：\n{content}"
    ),
    output_model=SilverQueryOutput,
)

SILVER_REVIEW_PROMPT = PromptSpec(
    key="evaluation.silver-review",
    version="1.0.1",
    instructions=(
        "你是独立的工程知识检索评测审核员。逐条判断问题是否忠实于给定知识、类型是否正确、"
        "正样本是否应命中该知识、困难负样本是否确实不应由该知识回答。"
        "如果负样本只是索要正文未提供的数值、反向询问正文结论或细化同一措施，必须 reject。不得因为问题语言通顺就通过。"
    ),
    template=(
        "独立复核以下白银评测候选。case_id 必须对应输入编号；decision 只能为 pass、reject 或 escalate。"
        "只有含义明确、预期命中关系正确且不引入资料外事实时才能 pass。"
        "必须只输出 JSON，完整包含 case_id、decision、confidence、issues。示例："
        '{{"reviews":[{{"case_id":1,"decision":"pass","confidence":0.96,"issues":[]}}]}}。\n\n'
        "已发布知识与候选问题：\n{review_material}"
    ),
    output_model=SilverReviewOutput,
)

KNOWLEDGE_EXTRACTION_PROMPT = PromptSpec(
    key="knowledge.extract-candidates",
    version="1.1.1",
    instructions=(
        "你是建设工程知识工程师。只提取原文明确支持、可跨项目复用的知识；不得补充原文没有的参数、"
        "规范编号、设备数量、工期或承诺。每条候选必须绑定一个章节编号和逐字来源引文。"
    ),
    template=(
        "从以下标准文档拆解不超过{max_candidates}条独立候选知识。content应删除具体项目、客户、地域和人员，"
        "但不得改变技术含义；source_quote必须逐字取自对应章节。输出JSON对象，字段为candidates；每条包含"
        "source_section_id、title、unit_type、content、summary、tags、applicability、risk_level、source_quote。"
        "content至少包含20个中文字符，必须是可独立理解的完整表述。"
        "risk_level必须输出英文枚举low、medium或high，不要输出中文。风险判定："
        "low仅用于表格结构、组织方式和不含技术参数的通用管理模式；"
        "medium用于原文充分支持、无阈值参数且适用范围明确的常规技术方法；"
        "high用于安全或结构关键措施、计算与专项方案、法规验收阈值、设备能力、具体数值或强承诺。"
        "unit_type只能使用construction_method、quality_control、safety_measure、schedule_plan、resource_plan、"
        "organization_chart、process_flow、site_layout、table_template、management_measure。\n\n"
        "文档标题：{document_title}\n行业：{industry}\n章节原文：\n{section_text}"
    ),
    output_model=KnowledgeExtractionOutput,
)

KNOWLEDGE_REVIEW_PROMPT = PromptSpec(
    key="knowledge.review-candidates",
    version="1.0.2",
    instructions=(
        "你是独立的建设工程知识复核人。逐条检查候选是否忠实原文、是否仍含项目特定事实、是否存在"
        "无依据参数或强承诺、适用范围是否清楚。不得因为文本通顺而判定通过。"
    ),
    template=(
        "复核以下候选知识。candidate_index必须对应输入数组下标。decision只能为pass、revise、escalate或reject；"
        "只有原文充分支持且可复用时才能pass。输出JSON对象，字段为reviews；每条包含candidate_index、decision、"
        "confidence、issues和corrected_content。severity必须输出英文枚举low、medium或high；无需修订时corrected_content为空。\n\n"
        "来源章节：\n{section_text}\n\n候选数组：\n{candidate_json}"
    ),
    output_model=KnowledgeReviewOutput,
)

KNOWLEDGE_ADJUDICATION_PROMPT = PromptSpec(
    key="knowledge.adjudicate-low-risk",
    version="1.0.1",
    instructions=(
        "你是知识自动发布的最终独立裁决人。只判断低风险候选；必须再次核验逐字来源、技术含义、"
        "跨项目适用性和风险分级。发现任何参数、承诺、适用范围扩大或来源不足时不得通过。"
    ),
    template=(
        "对低风险候选进行最终裁决。candidate_index对应输入下标；只有来源充分、无需修改且确属低风险时输出pass，"
        "否则输出escalate或reject。必须只输出JSON对象，不得使用reason字段。每条reviews必须完整包含："
        "candidate_index整数、decision英文枚举、confidence为0到1之间的数字、issues数组、corrected_content字符串。"
        "即使issues为空、corrected_content为空，也必须显式输出这两个字段。示例："
        '{{"reviews":[{{"candidate_index":0,"decision":"pass","confidence":0.96,"issues":[],"corrected_content":""}}]}}。\n\n'
        "来源章节：\n{section_text}\n\n候选数组：\n{candidate_json}"
    ),
    output_model=KnowledgeReviewOutput,
)

KNOWLEDGE_FORMAL_REVIEW_PROMPT = PromptSpec(
    key="knowledge.formal-review",
    version="1.0.0",
    instructions=(
        "你是正式工程知识发布的最终独立裁决模型，不是人工审核人。逐字核验来源引文、技术含义、"
        "跨项目适用范围、所有数值与规范表述；禁止补充来源之外的事实。发现法律责任、版权、保密、"
        "个人信息、项目身份、无依据参数、绝对承诺或适用范围扩张时必须reject。"
    ),
    template=(
        "对候选知识作最终裁决。candidate_index对应输入下标；decision只能为pass、revise、escalate或reject。"
        "只有来源充分、适用范围清楚且可跨项目安全复用时才能pass。若仅需删除项目特定内容且不改变技术含义可revise，"
        "并在corrected_content给出完整修订稿。输出JSON对象reviews，每条完整包含candidate_index、decision、confidence、"
        "issues、corrected_content。\n\n来源章节：\n{section_text}\n\n候选数组：\n{candidate_json}"
    ),
    output_model=KnowledgeReviewOutput,
)


OutputT = TypeVar("OutputT", bound=BaseModel)


class AiRuntime:
    def __init__(self, db: Database, llm: LlmClient | None = None) -> None:
        self.db = db
        self.llm = llm or LlmClient()

    def register_prompts(self, *specs: PromptSpec) -> None:
        for spec in specs:
            self._register_prompt(spec)

    def execute(
        self,
        spec: PromptSpec,
        prompt: str,
        input_payload: dict[str, Any],
        *,
        task_type: str,
        target_type: str = "",
        target_id: int | None = None,
        max_output_tokens: int = 8000,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        self._register_prompt(spec)
        settings = self.llm.settings()
        input_json = json.dumps(
            {"payload": input_payload, "rendered_prompt": prompt},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        input_hash = content_hash(input_json)
        cache_key = content_hash(
            json.dumps(
                {
                    "task_type": task_type,
                    "prompt_hash": spec.prompt_hash,
                    "input_hash": input_hash,
                    "model": settings.get("model", ""),
                    "base_url": settings.get("base_url", ""),
                    "wire_api": settings.get("wire_api", ""),
                },
                sort_keys=True,
            )
        )
        if use_cache:
            cached = self._cached_run(cache_key)
            if cached:
                return self._record_cache_hit(spec, task_type, target_type, target_id, input_json, input_hash, cache_key, settings, cached)
            recovered = self._revalidate_failed_run(cache_key, spec)
            if recovered:
                return self._record_cache_hit(spec, task_type, target_type, target_id, input_json, input_hash, cache_key, settings, recovered)

        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_runs(
                    task_type,target_type,target_id,prompt_key,prompt_version,prompt_hash,input_hash,cache_key,
                    model,base_url,wire_api,status,input_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'running',?)
                """,
                (
                    task_type,
                    target_type,
                    target_id,
                    spec.key,
                    spec.version,
                    spec.prompt_hash,
                    input_hash,
                    cache_key,
                    settings.get("model", ""),
                    settings.get("base_url", ""),
                    settings.get("wire_api", ""),
                    input_json,
                ),
            )
            run_id = int(cursor.lastrowid)

        result = self.llm.generate(spec.instructions, prompt, max_output_tokens)
        output_text = str(result.get("content") or "")
        parsed = self.llm.json_payload(output_text) if output_text else None
        payload: dict[str, Any] | None = None
        validation_errors: list[dict[str, Any]] = []
        error_code = ""
        error_message = str(result.get("error") or "")
        if parsed is not None:
            payload, validation_errors = self._validate_payload(spec, parsed)
            if payload is None:
                error_code = "schema_validation_failed"
                error_message = "模型输出未通过结构化校验"
        elif output_text:
            error_code = "invalid_json"
            error_message = "模型输出不是有效JSON"
        else:
            error_code = "model_unavailable" if not settings.get("configured") else "model_call_failed"
            error_message = error_message or "模型未返回内容"

        if payload is None and error_code in {"schema_validation_failed", "invalid_json"}:
            retry_prompt = (
                f"{prompt}\n\n"
                "上次输出未通过JSON结构校验。请严格按照要求的JSON对象结构重新完整输出；"
                "不要使用Markdown代码块，不要省略必填字段，不要添加说明文字。"
            )
            retried = self.llm.generate(spec.instructions, retry_prompt, max_output_tokens)
            retry_text = str(retried.get("content") or "")
            retry_parsed = self.llm.json_payload(retry_text) if retry_text else None
            if retry_parsed is not None:
                retry_payload, retry_errors = self._validate_payload(spec, retry_parsed)
                if retry_payload is not None:
                    result = {
                        **retried,
                        "latency_ms": int(result.get("latency_ms") or 0) + int(retried.get("latency_ms") or 0),
                        "attempts": int(result.get("attempts") or 0) + int(retried.get("attempts") or 0),
                        "input_tokens": int(result.get("input_tokens") or 0) + int(retried.get("input_tokens") or 0),
                        "output_tokens": int(result.get("output_tokens") or 0) + int(retried.get("output_tokens") or 0),
                    }
                    output_text = retry_text
                    payload = retry_payload
                    validation_errors = retry_errors
                    error_code = ""
                    error_message = ""

        status = "succeeded" if payload is not None else "failed"
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE ai_runs SET status=?,output_text=?,output_json=?,validation_errors_json=?,error_code=?,
                    error_message=?,latency_ms=?,attempts=?,input_tokens=?,output_tokens=?,completed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    status,
                    output_text,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    json.dumps(validation_errors, ensure_ascii=False),
                    error_code,
                    error_message,
                    int(result.get("latency_ms") or 0),
                    int(result.get("attempts") or 0),
                    int(result.get("input_tokens") or 0),
                    int(result.get("output_tokens") or 0),
                    run_id,
                ),
            )
        return {
            **result,
            "run_id": run_id,
            "payload": payload,
            "cached": False,
            "validation_errors": validation_errors,
            "error": error_message if payload is None else "",
        }

    def list_runs(self, limit: int = 100, status: str = "", task_type: str = "") -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if task_type:
            clauses.append("task_type=?")
            params.append(task_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id,task_type,target_type,target_id,prompt_key,prompt_version,input_hash,model,status,
                    error_code,error_message,latency_ms,attempts,input_tokens,output_tokens,cached_from_run_id,
                    created_at,completed_at
                FROM ai_runs {where} ORDER BY id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_prompts(self) -> list[dict[str, Any]]:
        return self.db.rows(
            "SELECT prompt_key,version,prompt_hash,status,created_at FROM ai_prompt_versions ORDER BY prompt_key,version DESC"
        )

    def metrics(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status='cached' THEN 1 ELSE 0 END) AS cached,
                    COALESCE(SUM(input_tokens),0) AS input_tokens,
                    COALESCE(SUM(output_tokens),0) AS output_tokens
                FROM ai_runs
                """
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def _register_prompt(self, spec: PromptSpec) -> None:
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT prompt_hash FROM ai_prompt_versions WHERE prompt_key=? AND version=?",
                (spec.key, spec.version),
            ).fetchone()
            if existing and existing["prompt_hash"] != spec.prompt_hash:
                raise RuntimeError(f"提示词{spec.key}@{spec.version}内容已变化，请提升版本号")
            conn.execute(
                """
                INSERT OR IGNORE INTO ai_prompt_versions(
                    prompt_key,version,instructions,template,output_schema_json,prompt_hash
                ) VALUES (?,?,?,?,?,?)
                """,
                (spec.key, spec.version, spec.instructions, spec.template, json.dumps(spec.schema, ensure_ascii=False), spec.prompt_hash),
            )

    def _cached_run(self, cache_key: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_runs WHERE cache_key=? AND status='succeeded' AND output_json IS NOT NULL ORDER BY id DESC LIMIT 1",
                (cache_key,),
            ).fetchone()
        return dict(row) if row else None

    def _revalidate_failed_run(self, cache_key: str, spec: PromptSpec) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_runs WHERE cache_key=? AND status='failed' AND output_text<>'' ORDER BY id DESC LIMIT 1",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        parsed = self.llm.json_payload(str(row["output_text"] or ""))
        if parsed is None:
            return None
        payload, validation_errors = self._validate_payload(spec, parsed)
        if payload is None:
            return None
        recovered = dict(row)
        recovered["output_json"] = json.dumps(payload, ensure_ascii=False)
        recovered["validation_errors_json"] = json.dumps(validation_errors, ensure_ascii=False)
        return recovered

    @staticmethod
    def _validate_payload(spec: PromptSpec, parsed: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        try:
            return spec.output_model.model_validate(parsed).model_dump(), []
        except ValidationError as exc:
            errors = [
                {"path": ".".join(str(value) for value in item["loc"]), "message": item["msg"], "type": item["type"]}
                for item in exc.errors()
            ]
        if spec.output_model is not KnowledgeExtractionOutput or set(parsed) != {"candidates"}:
            return None, errors
        raw_candidates = parsed.get("candidates")
        if not isinstance(raw_candidates, list):
            return None, errors
        valid_candidates: list[dict[str, Any]] = []
        isolated_errors: list[dict[str, Any]] = []
        for index, candidate in enumerate(raw_candidates):
            try:
                valid_candidates.append(KnowledgeExtractionCandidate.model_validate(candidate).model_dump())
            except ValidationError as exc:
                isolated_errors.extend(
                    {
                        "path": ".".join(["candidates", str(index), *(str(value) for value in item["loc"])]),
                        "message": item["msg"],
                        "type": item["type"],
                    }
                    for item in exc.errors()
                )
        return ({"candidates": valid_candidates}, isolated_errors) if valid_candidates else (None, isolated_errors or errors)

    def _record_cache_hit(
        self,
        spec: PromptSpec,
        task_type: str,
        target_type: str,
        target_id: int | None,
        input_json: str,
        input_hash: str,
        cache_key: str,
        settings: dict[str, Any],
        cached: dict[str, Any],
    ) -> dict[str, Any]:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_runs(
                    task_type,target_type,target_id,prompt_key,prompt_version,prompt_hash,input_hash,cache_key,
                    model,base_url,wire_api,status,input_json,output_text,output_json,validation_errors_json,
                    cached_from_run_id,completed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'cached',?,?,?,?,?,CURRENT_TIMESTAMP)
                """,
                (
                    task_type,
                    target_type,
                    target_id,
                    spec.key,
                    spec.version,
                    spec.prompt_hash,
                    input_hash,
                    cache_key,
                    settings.get("model", ""),
                    settings.get("base_url", ""),
                    settings.get("wire_api", ""),
                    input_json,
                    cached["output_text"],
                    cached["output_json"],
                    cached.get("validation_errors_json") or "[]",
                    cached["id"],
                ),
            )
            run_id = int(cursor.lastrowid)
        return {
            "run_id": run_id,
            "payload": json.loads(cached["output_json"]),
            "content": cached["output_text"],
            "model": settings.get("model", ""),
            "cached": True,
            "cached_from_run_id": cached["id"],
            "validation_errors": json.loads(cached.get("validation_errors_json") or "[]"),
            "error": "",
            "latency_ms": 0,
            "attempts": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
