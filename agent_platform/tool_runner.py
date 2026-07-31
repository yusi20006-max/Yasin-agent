"""
tool_runner.py
رجیستری ابزارهای نام‌گذاری‌شده که مراحل (steps) می‌توانند فراخوانی کنند.

هر ابزار یک تابع/callable ساده است با امضای دلخواه؛ فراخوانی از طریق نام
انجام می‌شود تا planner/executor نیازی به import مستقیم توابع نداشته باشند.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


class ToolNotFoundError(Exception):
    """وقتی ابزاری با نام درخواست‌شده ثبت نشده باشد."""


class ToolRunner:
    """رجیستری ساده‌ی نام -> callable."""

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, func: Callable[..., Any], overwrite: bool = False) -> None:
        if name in self._tools and not overwrite:
            raise ValueError(f"ابزار '{name}' قبلاً ثبت شده است (overwrite=True بدهید تا جایگزین شود)")
        self._tools[name] = func

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has_tool(self, name: str) -> bool:
        if name in self._tools:
            return True
        try:
            from agent_platform.integration import get_active_client
            client = get_active_client()
            if client and hasattr(client, "get_tool") and client.get_tool(name) is not None:
                return True
        except Exception:
            pass
        return False

    def list_tools(self) -> List[str]:
        tools = set(self._tools.keys())
        try:
            from agent_platform.integration import get_active_client
            client = get_active_client()
            if client and hasattr(client, "list_tools"):
                tools.update(client.list_tools())
        except Exception:
            pass
        return sorted(list(tools))

    def run(self, name: str, *args: Any, **kwargs: Any) -> Any:
        import inspect
        def filter_kwargs(func: Callable[..., Any], kw: Dict[str, Any]) -> Dict[str, Any]:
            try:
                sig = inspect.signature(func)
            except Exception:
                return kw
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if has_var_keyword:
                return kw
            valid_names = set(sig.parameters.keys())
            return {k: v for k, v in kw.items() if k in valid_names}

        if name not in self._tools:
            client = None
            try:
                from agent_platform.integration import get_active_client
                client = get_active_client()
            except Exception:
                pass

            if client and hasattr(client, "get_tool") and client.get_tool(name) is not None:
                target_tool = client.get_tool(name)
                func_to_inspect = target_tool
                if hasattr(target_tool, "func"):
                    func_to_inspect = target_tool.func
                elif hasattr(target_tool, "execute"):
                    func_to_inspect = target_tool.execute

                # Merge context parameters if they exist
                merged_kwargs = dict(kwargs)
                context_dict = kwargs.get("context", {})
                if isinstance(context_dict, dict):
                    for k, v in context_dict.items():
                        merged_kwargs.setdefault(k, v)

                filtered_kwargs = filter_kwargs(func_to_inspect, merged_kwargs)
                return client.execute_tool(name, *args, **filtered_kwargs)

            raise ToolNotFoundError(f"ابزار '{name}' ثبت نشده است. ابزارهای موجود: {self.list_tools()}")

        target_func = self._tools[name]
        filtered_kwargs = filter_kwargs(target_func, kwargs)
        return target_func(*args, **filtered_kwargs)
