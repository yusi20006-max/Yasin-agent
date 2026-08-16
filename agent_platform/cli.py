"""
cli.py
قلاب اتصال به CLI اصلی YasinAI برای دستور جدید:

    yasin agent run <agent_name>

این فایل هیچ منطق تجاری ندارد؛ فقط AgentRegistry + TemplatePlanner +
Executor را به هم وصل می‌کند. رجیستر کردن ابزارها و templateهای واقعی
باید جای دیگری (مثلاً در نقطه‌ی راه‌اندازی برنامه) انجام شود و از طریق
`build_default_registries` یا تزریق مستقیم در اختیار این تابع قرار گیرد.

نکته: این ماژول دستور موجود `yasin agent create` را تغییر نمی‌دهد؛
فقط زیردستور `run` را اضافه می‌کند.
"""

from __future__ import annotations

import sys
from typing import Optional

from .agent_registry import AgentConfig, AgentRegistry
from .executor import Executor
from .planner import Step, TemplatePlanner
from .task import Task, TaskResult
from .tool_runner import ToolRunner

# Local demo tool backends only (FINAL-G2 / #22).
# Do NOT import Yasin-AI private packages (knowledge_platform / security_platform /
# developer_platform). Agent runtime is Core-based; Yasin-AI GenerationService is
# NOT PLANNED until a concrete public-contract need is issued separately.
class _LocalKnowledgeTools:
    @staticmethod
    def fetch_news(source: str = "default") -> str:
        return f"خبر خام از منبع {source}"

    @staticmethod
    def translate(text: str, target_lang: str = "fa") -> str:
        return f"ترجمه‌شده به {target_lang}({text})"

    @staticmethod
    def summarize(text: str) -> str:
        return f"خلاصه({text})"


class _LocalSecurityTools:
    @staticmethod
    def check_content(text: str) -> bool:
        lower_text = text.lower()
        if any(word in lower_text for word in ["harmful", "spam", "bad"]):
            return False
        return True


class _LocalDeveloperTools:
    @staticmethod
    def publish(text: str) -> str:
        return f"انتشاریافته: {text}"


knowledge_platform = _LocalKnowledgeTools()
security_platform = _LocalSecurityTools()
developer_platform = _LocalDeveloperTools()


# Define default tools mapping to the respective platform APIs
def fetch_news_tool(context: dict, previous_output=None, source: str = "main_feed", **kwargs) -> str:
    return knowledge_platform.fetch_news(source)


def check_content_tool(context: dict, previous_output=None, **kwargs) -> str:
    text_to_check = previous_output or context.get("news_text", "")
    is_safe = security_platform.check_content(text_to_check)
    if not is_safe:
        raise ValueError("محتوا ناامن تشخیص داده شد")
    return text_to_check


def translate_tool(context: dict, previous_output=None, target_lang: str = "fa", **kwargs) -> str:
    text_to_translate = previous_output or ""
    return knowledge_platform.translate(text_to_translate, target_lang)


def summarize_tool(context: dict, previous_output=None, **kwargs) -> str:
    text_to_summarize = previous_output or ""
    return knowledge_platform.summarize(text_to_summarize)


def publish_tool(context: dict, previous_output=None, **kwargs) -> str:
    text_to_publish = previous_output or ""
    return developer_platform.publish(text_to_publish)


def build_default_registries() -> tuple[AgentRegistry, TemplatePlanner, ToolRunner]:
    """
    ساخت و مقداردهی اولیه به رجیستری ابزارها، پلنر و ایجنت‌ها با مقادیر پیش‌فرض.
    """
    tool_runner = ToolRunner()
    tool_runner.register("fetch_news", fetch_news_tool)
    tool_runner.register("check_content", check_content_tool)
    tool_runner.register("translate", translate_tool)
    tool_runner.register("summarize", summarize_tool)
    tool_runner.register("publish", publish_tool)

    planner = TemplatePlanner()
    # Flow: fetch_news -> check_content -> translate -> summarize -> publish
    planner.register_template(
        "news_flow",
        [
            Step(name="fetch_news", tool="fetch_news", args={"source": "main_feed"}, max_retries=2),
            Step(name="check_content", tool="check_content"),
            Step(name="translate", tool="translate", args={"target_lang": "fa"}),
            Step(name="summarize", tool="summarize"),
            Step(name="publish", tool="publish"),
        ]
    )

    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentConfig(
            name="news_bot",
            goal="news_flow",
            description="بات اجرای خودکار دریافت، بررسی امنیت، ترجمه، خلاصه‌سازی و انتشار خبر",
            default_context={"news_text": ""}
        )
    )

    return agent_registry, planner, tool_runner


def run_agent(
    agent_name: str,
    agent_registry: AgentRegistry,
    planner: TemplatePlanner,
    tool_runner: ToolRunner,
    task_name: Optional[str] = None,
) -> TaskResult:
    """
    اجرای یک ایجنت با نام مشخص: goal آن را از registry می‌گیرد،
    پلن می‌سازد، و با Executor اجرا می‌کند.

    این تابع همان چیزی است که دستور CLI `yasin agent run <name>` باید
    صدا بزند.
    """
    config = agent_registry.get(agent_name)
    task = Task(
        name=task_name or agent_name,
        goal=config.goal,
        context=dict(config.default_context),
    )
    steps = planner.plan(config.goal)
    executor = Executor(tool_runner)
    return executor.run(task, steps)


def register_cli_command(cli_app) -> None:
    """
    نقطه‌ی الحاق به CLI موجود YasinAI.

    این تابع با ارزیابی شیء ورودی، دستور جدید را روی آن ثبت می‌کند تا با click،
    argparse یا سایر ساختارهای CLI سازگار باشد.
    """
    try:
        import click
    except ImportError:
        click = None

    class_name = cli_app.__class__.__name__

    is_click_group = False
    if click is not None:
        click_group_cls = getattr(click, "Group", None)
        if click_group_cls is not None and isinstance(cli_app, click_group_cls):
            is_click_group = True
        elif hasattr(cli_app, "command") and hasattr(cli_app, "group"):
            is_click_group = True

    if is_click_group:
        agent_group = cli_app.commands.get("agent")
        if agent_group is None:
            @cli_app.group("agent")
            def agent_group_func():
                """دستورات مربوط به مدیریت و اجرای ایجنت‌ها"""
                pass
            agent_group = agent_group_func

        @agent_group.command("run")
        @click.argument("agent_name")
        def run_command(agent_name):
            """اجرای یک ایجنت با نام مشخص"""
            click.echo(f"در حال اجرای ایجنت: {agent_name}...")
            agent_registry, planner, tool_runner = build_default_registries()
            try:
                result = run_agent(agent_name, agent_registry, planner, tool_runner)
                for r in result.step_results:
                    status_str = "موفق" if r.success else "ناموفق"
                    click.echo(f"مرحله '{r.step_name}': {status_str} (تلاش‌ها: {r.attempts})")
                    if r.error:
                        click.echo(f"  خطا: {r.error}")
                if result.success:
                    click.echo(f"ای‌جنت با موفقیت پایان یافت. خروجی نهایی: {result.output}")
                else:
                    click.echo(f"اجرای ایجنت با خطا مواجه شد: {result.error}")
            except Exception as e:
                click.echo(f"خطای غیرمنتظره: {e}")

    elif "ArgumentParser" in class_name or hasattr(cli_app, "add_subparsers"):
        subparsers = None
        for action in cli_app._actions:
            if action.__class__.__name__ == "_SubParsersAction":
                subparsers = action
                break

        if subparsers is None:
            subparsers = cli_app.add_subparsers(dest="command")

        agent_parser = subparsers.choices.get("agent")
        if agent_parser is None:
            agent_parser = subparsers.add_parser("agent", help="دستورات ایجنت")

        agent_subparsers = None
        for action in agent_parser._actions:
            if action.__class__.__name__ == "_SubParsersAction":
                agent_subparsers = action
                break

        if agent_subparsers is None:
            agent_subparsers = agent_parser.add_subparsers(dest="agent_command")

        if "run" not in agent_subparsers.choices:
            run_parser = agent_subparsers.add_parser("run", help="اجرای یک ایجنت با نام مشخص")
            run_parser.add_argument("agent_name", help="نام ایجنت")


def main() -> None:
    """اجرای مستقیم CLI به کمک argparse."""
    import argparse
    parser = argparse.ArgumentParser(description="Yasin Agent CLI")
    register_cli_command(parser)
    args = parser.parse_args()

    if getattr(args, "command", None) == "agent" and getattr(args, "agent_command", None) == "run":
        agent_name = args.agent_name
        print(f"در حال اجرای ایجنت: {agent_name}...")
        agent_registry, planner, tool_runner = build_default_registries()
        try:
            result = run_agent(agent_name, agent_registry, planner, tool_runner)
            for r in result.step_results:
                status_str = "موفق" if r.success else "ناموفق"
                print(f"مرحله '{r.step_name}': {status_str} (تلاش‌ها: {r.attempts})")
                if r.error:
                    print(f"  خطا: {r.error}")
            if result.success:
                print(f"ای‌جنت با موفقیت پایان یافت. خروجی نهایی: {result.output}")
                sys.exit(0)
            else:
                print(f"اجرای ایجنت با خطا مواجه شد: {result.error}")
                sys.exit(1)
        except Exception as e:
            print(f"خطای غیرمنتظره: {e}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
