"""Read-only discovery and normalization of local coding-agent session files."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LocalSessionNotFoundError(LookupError):
    """Raised when a requested local Agent session no longer exists."""


_SESSION_ID = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_ENVIRONMENT_BLOCK = re.compile(
    r"<environment_context>.*?</environment_context>",
    re.IGNORECASE | re.DOTALL,
)
_INSTRUCTION_BLOCK = re.compile(
    r"<(?:permissions|developer|system)[^>]*>.*?</(?:permissions|developer|system)>",
    re.IGNORECASE | re.DOTALL,
)
_WHITESPACE = re.compile(r"\s+")

_SOURCE_NAMES = {
    "codex": "Codex",
    "claude-code": "Claude Code",
    "pi": "Pi",
}


class LocalSessionService:
    """Discover local Agent histories without modifying vendor-owned files."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home or Path.home()).expanduser()
        self._summary_cache: dict[tuple[str, str, int, int], dict[str, Any]] = {}

    def list_sessions(
        self,
        *,
        source: str | None = None,
        query: str | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        allowed = {source} if source else set(_SOURCE_NAMES)
        sessions: list[dict[str, Any]] = []
        if "codex" in allowed:
            sessions.extend(self._codex_summaries())
        if "claude-code" in allowed:
            sessions.extend(self._claude_summaries())
        if "pi" in allowed:
            sessions.extend(self._pi_summaries())

        source_counts: dict[str, int] = {}
        for item in sessions:
            source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1

        needle = (query or "").strip().lower()
        if needle:
            sessions = [
                item
                for item in sessions
                if needle
                in " ".join(
                    str(item.get(key) or "")
                    for key in ("title", "preview", "cwd", "source_name", "model")
                ).lower()
            ]
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        sessions = sessions[: max(1, min(limit, 1000))]
        return {
            "sessions": sessions,
            "home": str(self.home),
            "sources": [
                {
                    "id": source_id,
                    "name": name,
                    "count": source_counts.get(source_id, 0),
                }
                for source_id, name in _SOURCE_NAMES.items()
                if source_counts.get(source_id, 0) > 0
            ],
        }

    def get_session(self, source: str, session_id: str) -> dict[str, Any]:
        if source not in _SOURCE_NAMES:
            raise LocalSessionNotFoundError(f"unsupported session source: {source}")
        safe_id = session_id.strip().lower()
        if not _SESSION_ID.fullmatch(safe_id):
            raise LocalSessionNotFoundError("invalid session id")

        if source == "codex":
            path = self._find_codex_path(safe_id)
            if path is None:
                raise LocalSessionNotFoundError("session not found")
            summary, messages = self._parse_codex(path, include_messages=True)
        elif source == "claude-code":
            path = self._find_file(
                self.home / ".claude" / "projects",
                f"{safe_id}.jsonl",
                exclude_parts={"subagents"},
            )
            if path is None:
                raise LocalSessionNotFoundError("session not found")
            summary, messages = self._parse_claude(path, include_messages=True)
        else:
            path = self._find_file(
                self.home / ".pi" / "agent" / "sessions",
                "*",
                suffix=f"_{safe_id}.jsonl",
            )
            if path is None:
                raise LocalSessionNotFoundError("session not found")
            summary, messages = self._parse_pi(path, include_messages=True)

        return {**summary, "messages": messages[-200:]}

    def _codex_summaries(self) -> list[dict[str, Any]]:
        index = self._read_codex_index()
        summaries: list[dict[str, Any]] = []
        for path in self._codex_paths():
            session_id = self._id_from_path(path)
            if session_id is None:
                continue
            try:
                summary = self._cached_summary(
                    "codex",
                    path,
                    lambda path=path, session_id=session_id: self._codex_summary(
                        path,
                        index=index,
                        session_id=session_id,
                    ),
                )
            except OSError:
                continue
            summaries.append(summary)
        return self._deduplicate(summaries)

    def _codex_summary(
        self,
        path: Path,
        *,
        index: dict[str, dict[str, Any]],
        session_id: str,
    ) -> dict[str, Any]:
        row = next(_json_lines(path), {})
        payload = row.get("payload") if row.get("type") == "session_meta" else {}
        metadata = payload if isinstance(payload, dict) else {}
        indexed = index.get(session_id, {})
        first_user = self._codex_first_prompt(path)
        title = (
            _text(indexed.get("title"))
            or _title_from_text(first_user)
            or f"Codex 会话 {session_id[:8]}"
        )
        return _summary(
            source="codex",
            session_id=session_id,
            title=title,
            preview=_preview(first_user) or title,
            cwd=_text(metadata.get("cwd")),
            updated_at=_latest_iso(indexed.get("updated_at"), _mtime_iso(path)),
            message_count=None,
            user_message_count=0,
            model=None,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            archived="archived_sessions" in path.parts,
            subagent=metadata.get("thread_source") == "subagent",
            parent_session_id=_text(metadata.get("parent_thread_id")),
        )

    def _codex_first_prompt(self, path: Path) -> str:
        for index, row in enumerate(_json_lines(path)):
            if index > 500:
                break
            if row.get("type") != "response_item":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            message = self._codex_message(payload)
            if message is not None and message["role"] == "user":
                return message["content"]
        return ""

    def _claude_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        root = self.home / ".claude" / "projects"
        for path in self._files(root, "*.jsonl", exclude_parts={"subagents"}):
            try:
                summary = self._cached_summary(
                    "claude-code",
                    path,
                    lambda path=path: self._parse_claude(
                        path,
                        include_messages=False,
                    )[0],
                )
            except OSError:
                continue
            summaries.append(summary)
        return self._deduplicate(summaries)

    def _pi_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        root = self.home / ".pi" / "agent" / "sessions"
        for path in self._files(root, "*.jsonl"):
            try:
                summary = self._cached_summary(
                    "pi",
                    path,
                    lambda path=path: self._parse_pi(
                        path,
                        include_messages=False,
                    )[0],
                )
            except OSError:
                continue
            summaries.append(summary)
        return self._deduplicate(summaries)

    def _parse_codex(
        self,
        path: Path,
        *,
        include_messages: bool,
        index: dict[str, dict[str, Any]] | None = None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        metadata: dict[str, Any] = {}
        messages: list[dict[str, Any]] = []
        user_count = 0
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        model: str | None = None
        first_user: str | None = None
        for row in _json_lines(path):
            kind = row.get("type")
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if kind == "session_meta":
                metadata = payload
            elif kind == "turn_context":
                model = model or _text(payload.get("model"))
            elif kind == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info")
                usage = info.get("total_token_usage") if isinstance(info, dict) else None
                if isinstance(usage, dict):
                    input_tokens = _int(usage.get("input_tokens"))
                    output_tokens = _int(usage.get("output_tokens"))
                    total_tokens = _int(usage.get("total_tokens"))
            elif kind == "response_item":
                message = self._codex_message(payload)
                if message is None:
                    continue
                if message["role"] == "user":
                    user_count += 1
                    first_user = first_user or message["content"]
                if include_messages:
                    messages.append(message)

        resolved_id = str(metadata.get("id") or session_id or self._id_from_path(path) or "")
        if not resolved_id:
            raise OSError(f"cannot determine Codex session id: {path}")
        indexed = (index or {}).get(resolved_id, {})
        title = (
            _text(indexed.get("title"))
            or _title_from_text(first_user or "")
            or "Codex 会话"
        )
        updated = _latest_iso(
            indexed.get("updated_at"),
            _mtime_iso(path),
        )
        summary = _summary(
            source="codex",
            session_id=resolved_id,
            title=title,
            preview=_preview(first_user or "") or title,
            cwd=_text(metadata.get("cwd")),
            updated_at=updated,
            message_count=len(messages) if include_messages else None,
            user_message_count=user_count,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            archived="archived_sessions" in path.parts,
            subagent=metadata.get("thread_source") == "subagent",
            parent_session_id=_text(metadata.get("parent_thread_id")),
        )
        return summary, messages

    @staticmethod
    def _codex_message(payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("type") != "message":
            return None
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return None
        text = _content_text(payload.get("content"), role=role)
        text = _clean_prompt(text)
        if not text:
            return None
        return {
            "role": role,
            "content": text,
            "timestamp": None,
        }

    def _parse_claude(
        self,
        path: Path,
        *,
        include_messages: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        messages: list[dict[str, Any]] = []
        cwd: str | None = None
        model: str | None = None
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        cost_usd: float | None = None
        first_timestamp: str | None = None
        user_count = 0
        first_user: str | None = None

        for row in _json_lines(path):
            row_type = row.get("type")
            if row_type == "user":
                if row.get("isSidechain"):
                    continue
                origin = row.get("origin")
                if isinstance(origin, dict) and origin.get("kind") not in {None, "human"}:
                    continue
                message = row.get("message")
                text = _content_text(
                    message.get("content") if isinstance(message, dict) else None,
                    role="user",
                )
                text = _clean_prompt(text)
                if not text:
                    continue
                user_count += 1
                first_user = first_user or text
                cwd = cwd or _text(row.get("cwd"))
                first_timestamp = first_timestamp or _text(row.get("timestamp"))
                if include_messages:
                    messages.append(
                        {
                            "role": "user",
                            "content": text,
                            "timestamp": _text(row.get("timestamp")),
                        }
                    )
            elif row_type == "assistant":
                message = row.get("message")
                if not isinstance(message, dict):
                    continue
                model = model or _text(message.get("model"))
                if include_messages:
                    text = _content_text(message.get("content"), role="assistant")
                    if text:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": text,
                                "timestamp": _text(row.get("timestamp")),
                            }
                        )
            elif row_type == "cost-state":
                totals = _claude_usage_totals(row.get("modelUsage"))
                input_tokens = totals[0]
                output_tokens = totals[1]
                total_tokens = input_tokens + output_tokens
                cost_usd = _float(row.get("totalCostUSD"))

        session_id = self._id_from_path(path)
        if session_id is None:
            raise OSError(f"cannot determine Claude session id: {path}")
        title = _title_from_text(first_user or "") or "Claude Code 会话"
        summary = _summary(
            source="claude-code",
            session_id=session_id,
            title=title,
            preview=_preview(first_user or "") or title,
            cwd=cwd or _decode_project_directory(path.parent.name),
            updated_at=_mtime_iso(path),
            message_count=len(messages) if include_messages else None,
            user_message_count=user_count,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            archived=False,
            created_at=first_timestamp,
        )
        return summary, messages

    def _parse_pi(
        self,
        path: Path,
        *,
        include_messages: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        messages: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        model: str | None = None
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        cost_usd: float | None = None
        user_count = 0
        first_user: str | None = None

        for row in _json_lines(path):
            row_type = row.get("type")
            if row_type == "session":
                metadata = row
            elif row_type == "model_change":
                model = _text(row.get("modelId")) or _text(row.get("model"))
            elif row_type == "message":
                message = row.get("message")
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _content_text(message.get("content"), role=role)
                text = _clean_prompt(text)
                if not text:
                    continue
                if role == "user":
                    user_count += 1
                    first_user = first_user or text
                usage = message.get("usage")
                if isinstance(usage, dict):
                    input_tokens = _int(usage.get("input")) or input_tokens
                    output_tokens = _int(usage.get("output")) or output_tokens
                    total_tokens = _int(usage.get("totalTokens")) or total_tokens
                    cost = usage.get("cost")
                    if isinstance(cost, dict):
                        cost_usd = (
                            _float(cost.get("input"))
                            + _float(cost.get("output"))
                            + _float(cost.get("cacheRead"))
                            + _float(cost.get("cacheWrite"))
                        )
                if include_messages:
                    messages.append(
                        {
                            "role": role,
                            "content": text,
                            "timestamp": _text(row.get("timestamp")),
                        }
                    )

        session_id = _text(metadata.get("id")) or self._id_from_path(path)
        if not session_id:
            raise OSError(f"cannot determine Pi session id: {path}")
        title = _title_from_text(first_user or "") or "Pi 会话"
        summary = _summary(
            source="pi",
            session_id=session_id,
            title=title,
            preview=_preview(first_user or "") or title,
            cwd=_text(metadata.get("cwd")),
            updated_at=_mtime_iso(path),
            message_count=len(messages) if include_messages else None,
            user_message_count=user_count,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            archived=False,
            created_at=_text(metadata.get("timestamp")),
        )
        return summary, messages

    def _read_codex_index(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        path = self.home / ".codex" / "session_index.jsonl"
        for row in _json_lines(path):
            session_id = _text(row.get("id"))
            if not session_id:
                continue
            result[session_id] = {
                "title": _text(row.get("thread_name")),
                "updated_at": _text(row.get("updated_at")),
            }
        return result

    def _codex_paths(self) -> list[Path]:
        paths = self._files(self.home / ".codex" / "sessions", "*.jsonl")
        paths.extend(self._files(self.home / ".codex" / "archived_sessions", "*.jsonl"))
        return paths

    def _find_codex_path(self, session_id: str) -> Path | None:
        return next(
            (path for path in self._codex_paths() if self._id_from_path(path) == session_id),
            None,
        )

    def _find_file(
        self,
        root: Path,
        pattern: str,
        *,
        exclude_parts: set[str] | None = None,
        suffix: str | None = None,
    ) -> Path | None:
        for path in self._files(root, pattern, exclude_parts=exclude_parts):
            if suffix is None or path.name.endswith(suffix):
                return path
        return None

    def _cached_summary(
        self,
        source: str,
        path: Path,
        loader: Any,
    ) -> dict[str, Any]:
        stat = path.stat()
        key = (source, str(path), stat.st_mtime_ns, stat.st_size)
        if key not in self._summary_cache:
            self._summary_cache[key] = loader()
        return dict(self._summary_cache[key])

    @staticmethod
    def _files(
        root: Path,
        pattern: str,
        *,
        exclude_parts: set[str] | None = None,
    ) -> list[Path]:
        if not root.is_dir():
            return []
        excluded = exclude_parts or set()
        paths = [
            path
            for path in root.rglob(pattern)
            if path.is_file() and not excluded.intersection(path.parts)
        ]
        return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)

    @staticmethod
    def _id_from_path(path: Path) -> str | None:
        match = _SESSION_ID.search(path.stem)
        return match.group(1).lower() if match else None

    @staticmethod
    def _deduplicate(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            key = item["id"]
            current = result.get(key)
            if current is None or item["updated_at"] > current["updated_at"]:
                result[key] = item
        return list(result.values())


def _summary(
    *,
    source: str,
    session_id: str,
    title: str,
    preview: str,
    cwd: str | None,
    updated_at: str,
    message_count: int | None,
    user_message_count: int,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    archived: bool,
    cost_usd: float | None = None,
    created_at: str | None = None,
    subagent: bool = False,
    parent_session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{source}:{session_id}",
        "source": source,
        "source_name": _SOURCE_NAMES[source],
        "session_id": session_id,
        "title": title,
        "preview": preview,
        "cwd": cwd,
        "created_at": created_at,
        "updated_at": updated_at,
        "message_count": message_count,
        "user_message_count": user_message_count,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "archived": archived,
        "subagent": subagent,
        "parent_session_id": parent_session_id,
    }


def _json_lines(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except FileNotFoundError:
        return


def _content_text(content: Any, *, role: str) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = _text(item.get("type"))
        if item_type in {"tool_use", "tool_result", "image", "input_image"}:
            continue
        text = _text(item.get("text")) or _text(item.get("content"))
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _clean_prompt(text: str) -> str:
    if not text:
        return ""
    value = _ENVIRONMENT_BLOCK.sub("", text)
    value = _INSTRUCTION_BLOCK.sub("", value)
    value = value.replace("<environment_context>", "").replace("</environment_context>", "")
    value = value.strip()
    if value.startswith(("<permissions instructions>", "<user_instructions>")):
        return ""
    if value.startswith(
        (
            "The following is the Codex agent history",
            "You are judging one planned coding-agent action",
            "Reviewed Codex session id",
        )
    ):
        return ""
    return value


def _title_from_text(text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if not collapsed:
        return ""
    return collapsed[:120] + ("…" if len(collapsed) > 120 else "")


def _preview(text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if not collapsed:
        return ""
    return collapsed[:240] + ("…" if len(collapsed) > 240 else "")


def _decode_project_directory(name: str) -> str | None:
    if not name.startswith("-"):
        return None
    return name.replace("-", "/")


def _claude_usage_totals(value: Any) -> tuple[int, int]:
    if not isinstance(value, dict):
        return 0, 0
    input_tokens = 0
    output_tokens = 0
    for usage in value.values():
        if not isinstance(usage, dict):
            continue
        input_tokens += _int(usage.get("inputTokens"))
        input_tokens += _int(usage.get("cacheReadInputTokens"))
        input_tokens += _int(usage.get("cacheCreationInputTokens"))
        output_tokens += _int(usage.get("outputTokens"))
        output_tokens += _int(usage.get("thinkingTokens"))
    return input_tokens, output_tokens


def _latest_iso(*values: str | None) -> str:
    valid = [_normalize_iso(value) for value in values if value]
    return max(valid) if valid else _now_iso()


def _normalize_iso(value: str) -> str:
    text = value.strip()
    if text.endswith("Z"):
        return text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "LocalSessionNotFoundError",
    "LocalSessionService",
]
