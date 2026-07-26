# agent_platform

بسته‌ی اجرای وظایف چندمرحله‌ای برای YasinAI (بخشی از ریپازیتوری Yasin-AI).

## نصب / استفاده محلی

این پوشه را داخل ریپازیتوری Yasin-AI کپی کنید (کنار پوشه‌های
`knowledge_platform/`, `security_platform/` و ...) و سپس:

```bash
pip install pytest
python3 -m pytest tests/ -v
```

## ساختار

```
agent_platform/
├── agent_platform/
│   ├── __init__.py
│   ├── task.py            # Task, TaskResult, StepResult
│   ├── state_machine.py   # چرخه‌ی عمر Task (PENDING..SUCCEEDED/FAILED)
│   ├── tool_runner.py     # رجیستری ابزارهای قابل فراخوانی
│   ├── planner.py         # TemplatePlanner: goal -> لیست Step
│   ├── executor.py        # اجرای Stepها با retry و توقف در خطا
│   ├── agent_registry.py  # پیکربندی ایجنت‌های نام‌گذاری‌شده
│   └── cli.py             # run_agent() + قلاب اتصال به CLI اصلی
├── tests/
│   └── test_agent_platform.py
├── conftest.py
└── README.md
```

## مثال سریع

```python
from agent_platform import TemplatePlanner, ToolRunner, Task, Executor, Step

tool_runner = ToolRunner()
tool_runner.register("fetch", lambda context, previous_output=None, **_: "raw-news")
tool_runner.register("translate", lambda context, previous_output=None, **_: f"fa({previous_output})")

planner = TemplatePlanner()
planner.register_template("read_translate", [
    Step(name="fetch", tool="fetch"),
    Step(name="translate", tool="translate"),
])

task = Task(name="demo", goal="read_translate")
result = Executor(tool_runner).run(task, planner.plan("read_translate"))
print(result.summary(), result.output)
```

## اتصال به CLI

`agent_platform.cli.run_agent(agent_name, agent_registry, planner, tool_runner)`
همان تابعی است که دستور جدید `yasin agent run <agent_name>` باید صدا
بزند. `register_cli_command` یک placeholder است که باید هنگام
یکپارچه‌سازی با فریم‌ورک CLI فعلی (click/argparse/typer) تکمیل شود.

## قیود رعایت‌شده طبق پلن

- بدون وابستگی خارجی جدید (فقط stdlib)
- بدون سرور/شبکه
- تمام کلاس‌ها/توابع ورودی-خروجی مشخص و مستقل از transport دارند
- knowledge_platform / security_platform / developer_platform لمس نشده‌اند
  (این پکیج مستقل ساخته شده تا در PR واقعی، فقط از API عمومی آن‌ها
  استفاده شود)
