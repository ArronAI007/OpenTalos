import json
from html import escape
from typing import Any

_CSS = """
body { font-family: 'Consolas', 'Monaco', monospace; padding: 20px; background: #1a1a1a; color: #e0e0e0; margin: 0; }
.header { background: #2a2a2a; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
.header h1 { margin: 0; color: #4af626; }
.events { background: #2a2a2a; padding: 20px; border-radius: 8px; }
.event { border: 1px solid #333; margin: 10px 0; padding: 15px; border-radius: 5px; background: #1a1a1a; }
.event-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.step { color: #888; font-size: 12px; }
.timestamp { color: #666; font-size: 11px; }
.event-type { color: #4af626; font-weight: bold; }
.toggle { cursor: pointer; color: #4af626; user-select: none; }
.toggle:hover { color: #6fff48; }
.details { display: none; margin-top: 10px; padding: 10px; background: #0d0d0d; border-radius: 5px; overflow-x: auto; }
.details pre { margin: 0; color: #e0e0e0; }
.tool-call { border-left: 3px solid #4af626; }
.tool-result { border-left: 3px solid #ffd700; }
.error { border-left: 3px solid #ff4444; background: #2a1a1a; }
.model-output { border-left: 3px solid #00bfff; }
.stats { background: #2a2a2a; padding: 20px; border-radius: 8px; margin-top: 20px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; margin: 15px 0; }
.stat { background: #1a1a1a; padding: 15px; border-radius: 5px; border-left: 3px solid #4af626; }
.stat .label { display: block; color: #888; font-size: 12px; margin-bottom: 5px; }
.stat .value { display: block; font-size: 22px; font-weight: bold; }
.tool-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
.tool-table th, .tool-table td { padding: 8px; text-align: left; border-bottom: 1px solid #333; }
.tool-table th { color: #4af626; }
.errors { list-style: none; padding: 0; }
.errors li { background: #331111; padding: 10px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #ff4444; }
"""

_EVENT_CSS_CLASS = {
    "tool_call": "tool-call",
    "tool_result": "tool-result",
    "error": "error",
    "model_output": "model-output",
}


def render_header(session_id: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Run {escape(session_id)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="header"><h1>Run: {escape(session_id)}</h1></div>
<div class="events">
"""


def render_event(record: dict[str, Any], index: int) -> str:
    event_type = record["event"]
    step = record.get("step")
    css_class = "event " + _EVENT_CSS_CLASS.get(event_type, "")
    details_id = f"details-{index}"
    # payload 里可能包含工具输出/模型原文等不受信内容，必须转义后再塞进 <pre>，
    # 参考实现直接把 json.dumps 结果原样写进 HTML，理论上能被内容注入。
    payload_json = escape(json.dumps(record.get("payload", {}), indent=2, ensure_ascii=False))

    return f"""
<div class="{css_class}">
  <div class="event-header">
    <span class="step">{f"Step {step}" if step else "-"}</span>
    <span class="timestamp">{escape(record["ts"])}</span>
    <span class="event-type">{escape(event_type)}</span>
    <span class="toggle" onclick="toggleDetails('{details_id}')">[details]</span>
  </div>
  <div id="{details_id}" class="details"><pre>{payload_json}</pre></div>
</div>
"""


def render_footer(stats: dict[str, Any]) -> str:
    tool_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{count}</td></tr>"
        for name, count in sorted(stats["tool_calls"].items(), key=lambda item: item[1], reverse=True)
    ) or '<tr><td colspan="2">No tool calls</td></tr>'

    error_section = ""
    if stats["errors"]:
        error_items = "".join(
            f"<li>Step {error.get('step', '?')}: "
            f"<strong>{escape(str(error.get('type', 'UNKNOWN')))}</strong> - {escape(str(error.get('message', '')))}</li>"
            for error in stats["errors"]
        )
        error_section = f'<h3>Errors ({len(stats["errors"])})</h3><ul class="errors">{error_items}</ul>'

    return f"""
</div>
<div class="stats">
  <h2>Session Stats</h2>
  <div class="stats-grid">
    <div class="stat"><span class="label">Steps</span><span class="value">{stats["total_steps"]}</span></div>
    <div class="stat"><span class="label">Tokens</span><span class="value">{stats["total_tokens"]:,}</span></div>
    <div class="stat"><span class="label">Cost</span><span class="value">${stats["total_cost"]:.4f}</span></div>
    <div class="stat"><span class="label">Duration</span><span class="value">{stats["duration_seconds"]:.1f}s</span></div>
    <div class="stat"><span class="label">Model calls</span><span class="value">{stats["model_calls"]}</span></div>
  </div>
  <h3>Tool Calls</h3>
  <table class="tool-table"><tr><th>Tool</th><th>Count</th></tr>{tool_rows}</table>
  {error_section}
</div>
<script>
function toggleDetails(id) {{
  const el = document.getElementById(id);
  el.style.display = (el.style.display === 'block') ? 'none' : 'block';
}}
</script>
</body>
</html>
"""
