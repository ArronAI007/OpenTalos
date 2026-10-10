"""极简进程内指标登记表：counter / observation（count+sum）/ gauge，导出 Prometheus 文本。

不引第三方库。调用方用少量固定标签（model/tool/status/method/path）保持基数可控——标签值
直接来自模型名/工具名/HTTP 路径，本应用基数很小。进程级单例 `metrics`。
"""

import threading


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _key(name: str, labels: dict | None) -> str:
    if not labels:
        return name
    inner = ",".join(f'{key}="{_escape(value)}"' for key, value in sorted(labels.items()))
    return f"{name}{{{inner}}}"


def _suffixed(key: str, suffix: str) -> str:
    if "{" in key:
        base, rest = key.split("{", 1)
        return f"{base}{suffix}{{{rest}"
    return f"{key}{suffix}"


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._observations: dict[str, tuple[int, float]] = {}
        self._gauges: dict[str, float] = {}
        self._types: dict[str, str] = {}

    def inc(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        key = _key(name, labels)
        with self._lock:
            self._types[name] = "counter"
            self._counters[key] = self._counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        key = _key(name, labels)
        with self._lock:
            self._types[name] = "summary"
            count, total = self._observations.get(key, (0, 0.0))
            self._observations[key] = (count + 1, total + value)

    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        key = _key(name, labels)
        with self._lock:
            self._types[name] = "gauge"
            self._gauges[key] = float(value)

    def render(self) -> str:
        """导出 Prometheus 文本（observation 用 summary 的 _count/_sum，不设分位桶）。"""
        with self._lock:
            lines: list[str] = []
            typed: set[str] = set()
            for key, value in sorted(self._counters.items()):
                base = key.split("{", 1)[0]
                if base not in typed:
                    lines.append(f"# TYPE {base} counter")
                    typed.add(base)
                lines.append(f"{key} {_fmt(value)}")
            for key, (count, total) in sorted(self._observations.items()):
                base = key.split("{", 1)[0]
                if base not in typed:
                    lines.append(f"# TYPE {base} summary")
                    typed.add(base)
                lines.append(f"{_suffixed(key, '_count')} {count}")
                lines.append(f"{_suffixed(key, '_sum')} {_fmt(total)}")
            for key, value in sorted(self._gauges.items()):
                base = key.split("{", 1)[0]
                if base not in typed:
                    lines.append(f"# TYPE {base} gauge")
                    typed.add(base)
                lines.append(f"{key} {_fmt(value)}")
            return "\n".join(lines) + ("\n" if lines else "")

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "observations": dict(self._observations),
                "gauges": dict(self._gauges),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._observations.clear()
            self._gauges.clear()
            self._types.clear()


metrics = Metrics()
