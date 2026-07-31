# agent_platform (Yasin-Agent) - نسخه ۱.۰.۰ پایدار

بسته‌ی پیشرفته و پایدار اجرای وظایف چندمرحله‌ای برای YasinAI (بخشی از ریپازیتوری Yasin-AI). این بسته لایه‌ی ارتباطی بین لایه‌های مختلف ایجنت، سیستم گردش کار، ابزارها، پلاگین‌ها، حافظه، کانتکست و SDK هسته (Yasin-Core SDK) را فراهم می‌سازد.

هدف اصلی طراحی این ریپازیتوری، استقلال کامل لایه پردازشی از CLI یا لایه‌های حمل‌ونقل شبکه (Transport-agnostic) است تا به سادگی بتوان یک لایه وب (مانند FastAPI) روی آن پیاده‌سازی کرد.

---

## ویژگی‌های کلیدی نسخه ۱.۰.۰ (v1.0 Stable Release)

- **لایه‌ی یکپارچه‌ساز ایجنت (Agent Definition Layer)**: تعریف ساختاریافته ایجنت‌ها شامل متادیتا (Metadata)، تنظیمات مدل و فنی (Configuration)، ویژگی‌های شخصیتی/پرسونا (Profile) و مدیریت قالب‌های پیشرفته پرامپت (PromptHandler).
- **سیستم گردش کار (Workflow/Planner)**: قابلیت تعریف پلن‌های ترتیبی با استفاده از `TemplatePlanner` و چرخه حیات مدیریت‌شده وضعیت کارهای تسک (`StateMachine`).
- **اجراکننده جریان کاری (Executor)**: پشتیبانی از اجرای گام‌به‌گام مراحل کاری همراه با اعتبارسنجی خروجی (Validators) و مکانیزم تلاش مجدد خطاها (Retries).
- **سیستم ابزارها (Tool System)**: ثبت و فراخوانی پویا با انطباق خودکار امضای متدها (`ToolRunner`) و قابلیت استفاده از ابزارهای ثبت‌شده در لایه SDK کلاینت.
- **سیستم پلاگین‌ها (Plugin System)**: کشف خودکار (Auto-discovery) پلاگین‌ها از دایرکتوری‌های مشخص، ثبت و اجرای پلاگین‌ها به کمک SDK کلاینت Yasin-Core.
- **حافظه و کانتکست (Memory & Context)**: مدیریت ایزوله و نخی کانتکست‌ها (`ContextManager`) و دسترسی به فضاهای حافظه کوتاه‌مدت و بلندمدت هسته (`MemoryManager`).
- **مدیریت نشست‌ها (Session Handling)**: قابلیت راه‌اندازی سشن‌های تعاملی مستقل با کانتکست و ایزوله‌سازی حافظه مجزا به همراه کلاس مدیر نشست‌ها (`SessionManager`).
- **یکپارچگی و آداپتور SDK**: آداپتور آماده `YasinCoreAgentAdapter` جهت تبدیل مستقیم ایجنت‌های پلتفرم به عنوان ایجنت معتبر در هسته Yasin-Core.

---

## ساختار پکیج

```
agent_platform/
├── agent_platform/
│   ├── __init__.py          # شناسه نسخه و صادرکننده رابط‌های عمومی
│   ├── agent_definition.py  # ساختار پیشرفته ایجنت (Metadata, Config, Profile, PromptHandler)
│   ├── agent_registry.py    # رجیستری و ثبت‌نام ایجنت‌ها (حالت ساده و پیشرفته دیتایی)
│   ├── task.py              # ساختار نگهداری وضعیت کارها (Task, TaskResult, StepResult)
│   ├── state_machine.py     # کنترل چرخه وضعیت کار (PENDING -> PLANNING -> RUNNING -> SUCCEEDED/FAILED)
│   ├── planner.py           # تعریف پلنر و گام‌های اجرایی (Step, TemplatePlanner)
│   ├── executor.py          # موتور اجرای ترتیبی گام‌ها به همراه retry و validation
│   ├── tool_runner.py       # رجیستری و مدیریت فراخوانی ابزارها با فیلتر پارامترها
│   ├── memory_context.py    # مدیریت حافظه، کانتکست پردازشی و سشن‌های ایزوله در سطح برنامه
│   ├── integration.py       # کدهای یکپارچه‌ساز و آداپتور با Yasin-Core SDK به همراه لایه Fallback
│   └── cli.py               # رابط خط فرمان، ساخت رجیستری‌های پیش‌فرض و الحاق به CLI کلی YasinAI
├── tests/                   # تست‌های کامل و جامع پکیج
│   ├── test_agent_platform.py   # تست‌های مستقل عملکردی لایه‌های ایجنت، پلنر، ماشین حالت و ابزارها
│   ├── test_memory_context.py   # تست‌های مدیریت حافظه، کانتکست‌ها و نشست‌های کاری ایزوله
│   └── test_integration.py      # تست‌های جامع یکپارچگی ابزارها، پلاگین‌ها، حافظه و آداپتور SDK
├── conftest.py              # تنظیمات لودر تست و ایجاد لایه mock پویا برای yasin_core
└── README.md                # مستندات راهنمای پروژه
```

---

## نصب و استفاده محلی

این پوشه را داخل ریپازیتوری Yasin-AI کپی کنید (کنار پوشه‌های `knowledge_platform/`، `security_platform/` و ...) و سپس وابستگی‌های توسعه را نصب کنید:

```bash
pip install pytest click
```

### اجرای تست‌ها
برای اطمینان از سلامت کامل ماژول‌ها و بخش‌های یکپارچه‌سازی، تست‌ها را اجرا کنید:

```bash
# اجرای تست‌ها در محیط جاری
pytest tests/ -v
```

---

## مثال‌های کاربردی

### ۱. تعریف و اجرای سریع یک جریان کار ساده

```python
from agent_platform import TemplatePlanner, ToolRunner, Task, Executor, Step

# ۱. تعریف و ثبت ابزارها
tool_runner = ToolRunner()
tool_runner.register("fetch", lambda context, previous_output=None, **_: "raw-news")
tool_runner.register("translate", lambda context, previous_output=None, **_: f"fa({previous_output})")

# ۲. پیکربندی جریان کار در پلنر
planner = TemplatePlanner()
planner.register_template("read_translate", [
    Step(name="fetch", tool="fetch"),
    Step(name="translate", tool="translate"),
])

# ۳. ساخت تسک و اجرای آن با استفاده از Executor
task = Task(name="demo", goal="read_translate")
result = Executor(tool_runner).run(task, planner.plan("read_translate"))

print(result.summary()) # موفقیت / شکست
print("خروجی نهایی:", result.output) # fa(raw-news)
```

### ۲. کار با سیستم نشست‌ها (Session) و ایزوله‌سازی حافظه

```python
from agent_platform import SessionManager

session_mgr = SessionManager()

# ایجاد یک نشست کاری منحصربه‌فرد با کانتکست اولیه
session = session_mgr.create_session("session_1001", {"user": "ali"})

# ذخیره داده‌ها در حافظه اختصاصی و ایزوله این سشن
session.save_short_term("selected_topic", "AI Technologies")
session.save_long_term("theme_preference", "dark")

# بازیابی مقادیر
topic = session.get_short_term("selected_topic")
theme = session.get_long_term("theme_preference")

print(f"Topic: {topic}, Theme: {theme}")

# اجرای یک تکه کد با کانتکست اختصاصی این سشن فعال
with session.run_with_context():
    # هر ماژولی در این بلاک از طریق get_current_context() به اطلاعات سشن دسترسی دارد
    pass
```

### ۳. یکپارچه‌سازی با Yasin-Core SDK

```python
from yasin_core.sdk import YasinCoreClient
from agent_platform import AgentRegistry, TemplatePlanner, ToolRunner, register_all_agents

# ساخت رجیستری‌ها
agent_registry = AgentRegistry()
planner = TemplatePlanner()
tool_runner = ToolRunner()

# ساخت کلاینت Yasin-Core
client = YasinCoreClient()

# ثبت خودکار تمام ابزارها و ایجنت‌های پلتفرم در کلاینت اصلی هسته
register_all_agents(client, agent_registry, planner, tool_runner)

# اکنون کلاینت هسته قادر به کشف و اجرای ایجنت‌های ثبت‌شده است
task = client.create_task(id="task-001", name="news_bot")
executed_task = client.execute_task(task)
print("وضعیت اجرا:", executed_task.status)
```

---

## اتصال به رابط خط فرمان (CLI)

`agent_platform.cli.run_agent(agent_name, agent_registry, planner, tool_runner)` تابع محوری خط فرمان است.

برای اجرای یک ایجنت پیش‌فرض از پیش تعریف‌شده (news_bot) مستقیماً از طریق CLI پروژه می‌توانید دستور زیر را وارد نمایید:

```bash
python -m agent_platform.cli agent run news_bot
```

تابع `register_cli_command(cli_app)` به صورت هوشمند نوع CLI فعلی پروژه (مانند click یا argparse) را ارزیابی کرده و دستور `agent run` را به آن اضافه می‌کند تا یکپارچگی خط فرمان در بالاترین سطح خود تضمین گردد.
