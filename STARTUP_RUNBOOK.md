# Yasin-Agent — Startup Runbook

این فایل مرجع عملیاتی اجرای Yasin-Agent در اکوسیستم Yasin است. هدف این است که نصب، تنظیم Token، اجرای HTTP runtime و اتصال به YasinHub در دفعات بعد بدون حدس‌زدن تکرار شود.

## 1. پیش‌نیازها

- Python 3.9 تا 3.14
- Termux/Android یا Linux
- مخزن در مسیر استاندارد اکوسیستم:

```text
~/yasineco/Yasin-agent
```

- برای HTTP server، extra مربوط به `server` باید نصب شده باشد.

## 2. ورود به مخزن

```bash
cd ~/yasineco/Yasin-agent
git status
git branch --show-current
```

## 3. ساخت/فعال‌سازی محیط Python

اگر `.venv` موجود است، از همان استفاده کنید. در صورت نیاز:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install -e '.[server]'
```

برای تست کامل:

```bash
python -m pip install -e '.[test-server]'
```

## 4. تست نصب

```bash
.venv/bin/python -c "import agent_platform, fastapi, uvicorn; print('YASIN_AGENT_IMPORTS_OK')"
```

و در صورت نصب وابستگی‌های تست:

```bash
.venv/bin/python -m pytest tests/ -q
```

## 5. Token — الزام امنیتی

HTTP runtime بدون `YASIN_AGENT_SERVICE_TOKEN` استارت نمی‌شود.

متغیر مورد نیاز:

```bash
export YASIN_AGENT_SERVICE_TOKEN='YOUR_TOKEN'
```

**توکن واقعی را داخل Git یا این فایل ثبت نکنید.**

در معماری YasinHub، توکن Agent و Hub باید یکسان باشند. YasinHub به‌صورت canonical از این فایل محلی استفاده می‌کند:

```text
~/.yasinhub/yasin-agent.token
```

اگر Hub این فایل را دارد، برای اجرای دستی Agent باید مقدار همان Token را در محیط قرار دهید:

```bash
export YASIN_AGENT_SERVICE_TOKEN="$(cat ~/.yasinhub/yasin-agent.token)"
```

## 6. اجرای HTTP Runtime — entry point تأییدشده

Entry point اصلی و تست‌شده:

```bash
cd ~/yasineco/Yasin-agent
.venv/bin/python -m agent_platform.server
```

Entry point جایگزین:

```bash
.venv/bin/yasin-agent-server
```

پیش‌فرض‌ها:

```text
Host: 127.0.0.1
Port: 8080
```

متغیرهای Host/Port:

```bash
export YASIN_AGENT_HOST=127.0.0.1
export YASIN_AGENT_PORT=8080
```

## 7. Health و Readiness

در ترمینال دوم:

```bash
TOKEN="$(cat ~/.yasinhub/yasin-agent.token)"
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/v1/health
```

سپس:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/v1/ready
```

انتظار:

```text
health: status=healthy
ready:  ready=true
```

پاسخ شامل متادیتای سیستم (`system`: `python_version`, `platform`, `arch`, `is_android`, `is_termux`, `android_api_level`) نیز می‌باشد.

اگر `Connection refused` گرفتید، اول بررسی کنید Process واقعاً در حال اجراست و Port 8080 آزاد/درست است.

## 8. اجرای استاندارد در اکوسیستم — از طریق YasinHub

در محیط عملیاتی، ترجیح این است که Yasin-Agent را مستقیماً از shell اجرا نکنید و YasinHub آن را به‌عنوان Service مدیریت کند:

```bash
cd ~/yasineco/YasinHub
python -m yasinhub.cli start yasin-agent
```

سپس:

```bash
python -m yasinhub.cli status
```

و Health/Readiness را با Token بررسی کنید.

## 9. تست واقعی Lifecycle

برای اثبات اینکه Service واقعاً اجرا/متوقف/Restart می‌شود:

```bash
cd ~/yasineco/YasinHub
python -m yasinhub.cli stop yasin-agent
python -m yasinhub.cli start yasin-agent
python -m yasinhub.cli restart yasin-agent
```

PID قبل و بعد از Restart باید متفاوت باشد. علاوه بر آن، `/v1/health` و `/v1/ready` باید بعد از Start پاسخ موفق بدهند.

## 10. اتصال YasinHub به Agent

سمت Hub:

```bash
export YASINHUB_AGENT_BASE_URL=http://127.0.0.1:8080
export YASINHUB_AGENT_SERVICE_TOKEN="$(cat ~/.yasinhub/yasin-agent.token)"
```

این Token باید با `YASIN_AGENT_SERVICE_TOKEN` سمت Agent یکسان باشد.

Health از سمت Hub باید از HTTP runtime احراز هویت‌شده عبور کند؛ مسیر اصلی Production، اتصال HTTP است، نه import مستقیم Runtime در همان Process.

## 11. خطاهای شناخته‌شده و راه‌حل

### Token missing

خطا:

```text
YASIN_AGENT_SERVICE_TOKEN is required to start the HTTP runtime adapter
```

راه‌حل:

```bash
export YASIN_AGENT_SERVICE_TOKEN="$(cat ~/.yasinhub/yasin-agent.token)"
```

### Port 8080 already in use

یعنی یک Agent یا Process دیگر احتمالاً روی 8080 اجراست. ابتدا Process موجود را شناسایی کنید و از اجرای Agent دوم خودداری کنید.

در محیط Yasin، اگر Agent قبلاً توسط runit/Termux service یا YasinHub مدیریت می‌شود، آن را دوباره دستی اجرا نکنید.

### بسته شدن Termux

Processهای foreground ممکن است با بسته شدن session از بین بروند. بعد از باز کردن Termux، همیشه این دو endpoint را دوباره بررسی کنید:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/v1/health
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/v1/ready
```

## 12. توقف دستی

اگر Agent در همان ترمینال اجرا شده است:

```text
Ctrl+C
```

در حالت Production/Control Plane، توقف را از Hub انجام دهید:

```bash
cd ~/yasineco/YasinHub
python -m yasinhub.cli stop yasin-agent
```

## 13. چک‌لیست شروع سریع دفعه بعد

```text
[ ] cd ~/yasineco/Yasin-agent
[ ] git status
[ ] .venv موجود و Python صحیح
[ ] server extra نصب است
[ ] pytest در صورت نیاز سبز است
[ ] ~/.yasinhub/yasin-agent.token موجود است
[ ] Token در environment قرار گرفته (برای اجرای دستی)
[ ] Port 8080 توسط Agent دیگری اشغال نیست
[ ] python -m agent_platform.server
[ ] /v1/health = healthy
[ ] /v1/ready = ready=true
[ ] Hub base URL = http://127.0.0.1:8080
[ ] Token سمت Hub و Agent یکسان است
[ ] Lifecycle با PID واقعی قابل اثبات است
```

## 14. اصل عملیاتی

**Yasin-Agent یک HTTP Runtime احراز هویت‌شده است؛ YasinHub کنترل‌کننده Lifecycle آن است.**

برای عملیات عادی: Hub را بالا بیاورید، سپس Agent را از Hub Start کنید و Health/Readiness را بررسی کنید. اجرای دستی Agent فقط برای نصب یا عیب‌یابی استفاده شود.
