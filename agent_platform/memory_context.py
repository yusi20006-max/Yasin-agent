"""
memory_context.py
مدیریت حافظه (Memory)، کانتکست (Context) و سشن‌ها (Sessions) در سطح اپلیکیشن برای agent_platform با استفاده از SDK عمومی Yasin-Core.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from agent_platform.integration import (
    YasinCoreClient,
    get_active_client,
    active_context,
    get_current_context,
)


class MemoryManager:
    """
    مدیریت دسترسی به حافظه کوتاه‌مدت و بلندمدت در سطح اپلیکیشن با استفاده از SDK کلاینت.
    """

    def __init__(self, client: Optional[YasinCoreClient] = None) -> None:
        self.client = client

    def _get_client(self) -> Optional[YasinCoreClient]:
        return self.client or get_active_client()

    def save(self, key: str, value: Any, category: str = "short-term") -> None:
        """ذخیره مقدار در حافظه کلاینت فعال."""
        client = self._get_client()
        if client and hasattr(client, "save_memory"):
            client.save_memory(key, value, category=category)
        else:
            raise RuntimeError("کلاینت فعال برای ذخیره حافظه یافت نشد.")

    def get(self, key: str, default: Any = None, category: str = "short-term") -> Any:
        """بازیابی مقدار از حافظه کلاینت فعال."""
        client = self._get_client()
        if client and hasattr(client, "get_memory"):
            return client.get_memory(key, default=default, category=category)
        return default


class ContextManager:
    """
    مدیریت ایجاد، بازخوانی و انتشار کانتکست‌های پردازشی با استفاده از SDK کلاینت.
    """

    def __init__(self, client: Optional[YasinCoreClient] = None) -> None:
        self.client = client

    def _get_client(self) -> Optional[YasinCoreClient]:
        return self.client or get_active_client()

    def create(self, data: Optional[Dict[str, Any]] = None) -> Any:
        """ایجاد یک کانتکست پردازشی جدید."""
        client = self._get_client()
        if client and hasattr(client, "create_context"):
            return client.create_context(data)

        # Public SDK boundary: no direct yasin_core.context import.
        # Without a Core client, use the local MockContext fallback.
        from agent_platform.integration import MockContext
        return MockContext(data)

    def propagate(self, context: Any) -> Any:
        """انتشار و اعمال کانتکست پردازشی در لایه جاری (استفاده به عنوان Context Manager)."""
        return active_context(context)

    @staticmethod
    def get_current() -> Any:
        """بازیابی کانتکست فعال در ریسه (thread) جاری."""
        return get_current_context()


class Session:
    """
    نمایشگر یک سشن (نشست تعاملی یا کاری) به همراه کانتکست و فضاهای حافظه اختصاصی.
    """

    def __init__(
        self,
        session_id: str,
        context_data: Optional[Dict[str, Any]] = None,
        client: Optional[YasinCoreClient] = None,
    ) -> None:
        self.session_id = session_id
        self.client = client or get_active_client()
        self.memory_manager = MemoryManager(self.client)

        # ساخت کانتکست برای سشن و قرار دادن شناسه سشن در آن
        ctx_data = dict(context_data) if context_data is not None else {}
        ctx_data["session_id"] = session_id

        # ایجاد کانتکست از طریق کلاینت یا به صورت دستی
        context_manager = ContextManager(self.client)
        self.context = context_manager.create(ctx_data)

    def save_short_term(self, key: str, value: Any) -> None:
        """ذخیره مقدار در حافظه کوتاه‌مدت اختصاصی این سشن (ایزوله‌سازی با پیشوند شناسه سشن)."""
        session_key = f"{self.session_id}:{key}"
        self.memory_manager.save(session_key, value, category="short-term")

    def get_short_term(self, key: str, default: Any = None) -> Any:
        """بازیابی مقدار از حافظه کوتاه‌مدت اختصاصی این سشن."""
        session_key = f"{self.session_id}:{key}"
        return self.memory_manager.get(session_key, default=default, category="short-term")

    def save_long_term(self, key: str, value: Any) -> None:
        """ذخیره مقدار در حافظه بلندمدت اختصاصی این سشن."""
        session_key = f"{self.session_id}:{key}"
        self.memory_manager.save(session_key, value, category="long-term")

    def get_long_term(self, key: str, default: Any = None) -> Any:
        """بازیابی مقدار از حافظه بلندمدت اختصاصی این سشن."""
        session_key = f"{self.session_id}:{key}"
        return self.memory_manager.get(session_key, default=default, category="long-term")

    def update_context(self, **kwargs: Any) -> None:
        """به‌روزرسانی مقادیر کانتکست سشن جاری."""
        for k, v in kwargs.items():
            self.context.set(k, v)

    def get_context_value(self, key: str, default: Any = None) -> Any:
        """دریافت یک مقدار از کانتکست سشن."""
        return self.context.get(key, default)

    def run_with_context(self) -> Any:
        """به اجرا درآوردن بلاک‌های برنامه در کانتکست اختصاصی این سشن."""
        return active_context(self.context)


class SessionManager:
    """
    مدیریت چرخه‌ی عمر و دسترسی به سشن‌های مختلف در سطح برنامه.
    """

    def __init__(self, client: Optional[YasinCoreClient] = None) -> None:
        self.client = client
        self._sessions: Dict[str, Session] = {}

    def create_session(self, session_id: str, context_data: Optional[Dict[str, Any]] = None) -> Session:
        """ایجاد یک سشن جدید با شناسه یکتا."""
        if session_id in self._sessions:
            raise ValueError(f"سشن با شناسه '{session_id}' از قبل وجود دارد.")
        session = Session(session_id, context_data, self.client)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """بازیابی یک سشن فعال بر اساس شناسه آن."""
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        """بستن و آزادسازی منابع یک سشن."""
        if session_id in self._sessions:
            # کانتکست سشن را پاک می‌کنیم
            session = self._sessions[session_id]
            if hasattr(session.context, "clear"):
                session.context.clear()
            del self._sessions[session_id]
