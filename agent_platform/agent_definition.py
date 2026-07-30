"""
agent_definition.py
تعریف لایه‌ی ایجنت (Agent Definition Layer) شامل پیکربندی، متادیتا، هندلینگ پرامپت و پروفایل‌ها.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from agent_platform.agent_registry import AgentConfig


class SafeDict(dict):
    """دیکشنری ایمن برای فرمت کردن پرامپت‌ها بدون پرتاب KeyError."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass
class AgentMetadata:
    """متادیتا و اطلاعات توصیفی ایجنت."""
    version: str = "1.0.0"
    author: str = "Yasin-Agent Developer"
    description: str = ""
    tags: List[str] = field(default_factory=list)
    custom_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentConfiguration:
    """تنظیمات فنی و اجرایی ایجنت."""
    model: str = "default-model"
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    timeout: float = 30.0
    extra_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentProfile:
    """پروفایل شخصیتی و رفتاری ایجنت (Persona/Profile)."""
    role: str = ""
    backstory: str = ""
    tone: str = "neutral"
    instructions: List[str] = field(default_factory=list)


class PromptHandler:
    """مدیریت و قالب‌بندی پرامپت‌های سیستم و کاربر."""

    def __init__(
        self,
        system_prompt_template: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        custom_templates: Optional[Dict[str, str]] = None,
    ):
        self.system_prompt_template = system_prompt_template or (
            "You are {role}. Your backstory is: {backstory}. "
            "Tone: {tone}. Instructions:\n{instructions}"
        )
        self.user_prompt_template = user_prompt_template or "Input: {input_data}"
        self.custom_templates = custom_templates or {}

    def render_system_prompt(self, profile: AgentProfile, **kwargs) -> str:
        """قالب‌بندی پرامپت سیستم با استفاده از پروفایل ایجنت."""
        instructions_str = ""
        if profile.instructions:
            instructions_str = "\n".join(f"- {inst}" for inst in profile.instructions)

        render_data = {
            "role": profile.role or "",
            "backstory": profile.backstory or "",
            "tone": profile.tone or "",
            "instructions": instructions_str,
        }
        render_data.update(kwargs)
        return self.system_prompt_template.format_map(SafeDict(render_data))

    def render_user_prompt(self, input_data: Any, **kwargs) -> str:
        """قالب‌بندی پرامپت کاربر."""
        render_data = {"input_data": input_data}
        render_data.update(kwargs)
        return self.user_prompt_template.format_map(SafeDict(render_data))

    def render_custom_prompt(self, template_name: str, **kwargs) -> str:
        """قالب‌بندی یکی از پرامپت‌های سفارشی ثبت‌شده."""
        if template_name not in self.custom_templates:
            raise ValueError(f"Prompt template '{template_name}' not found.")
        return self.custom_templates[template_name].format_map(SafeDict(kwargs))


class AgentDefinition(AgentConfig):
    """
    تعریف کامل یک ایجنت شامل پیکربندی، متادیتا، پروفایل و هندلر پرامپت.
    این کلاس از AgentConfig ارث‌بری می‌کند تا سازگاری کامل با سیستم ثبت و رجیستری فعلی حفظ شود.
    """

    def __init__(
        self,
        name: str,
        goal: str,
        description: str = "",
        default_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[AgentMetadata] = None,
        config: Optional[AgentConfiguration] = None,
        profile: Optional[AgentProfile] = None,
        prompt_handler: Optional[PromptHandler] = None,
    ):
        # ارجاع توضیحات به متادیتا در صورت عدم تعریف مستقیم
        actual_description = description or (metadata.description if metadata else "")
        super().__init__(
            name=name,
            goal=goal,
            description=actual_description,
            default_context=default_context or {},
        )
        self.metadata = metadata or AgentMetadata(description=actual_description)
        self.config = config or AgentConfiguration()
        self.profile = profile or AgentProfile()
        self.prompt_handler = prompt_handler or PromptHandler()
