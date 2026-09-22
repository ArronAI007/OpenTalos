import httpx
from pydantic import ValidationError

from .models import RunScriptRequest, RunScriptResponse, SkillSummary

DEFAULT_TIMEOUT_SECONDS = 60.0


class SkillServiceError(RuntimeError):
    """skill 服务不可达或返回了错误。message 面向调用方（最终可能原样喂给模型）。"""


class SkillClient:
    """skill 服务（skill.main:app）的异步 HTTP 客户端。

    测试可以通过 client 参数注入一个自定义 httpx.AsyncClient（如 MockTransport），
    不依赖真实服务和 Docker。
    """

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # base_url 始终由本类持有并拼出绝对 URL：注入的 client 只当传输层用
        # （比如测试里的 MockTransport 客户端没有 base_url，相对路径会直接报错）。
        # 超时要盖过服务端脚本的默认执行时限（10s）加容器冷启动开销，不能用 httpx 默认的 5s。
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def list_skills(self) -> list[SkillSummary]:
        data = await self._request("GET", "/skills")
        return [SkillSummary.model_validate(item) for item in data["skills"]]

    async def read_skill(self, skill_name: str) -> str:
        data = await self._request("GET", f"/skills/{skill_name}")
        return data["content"]

    async def run_script(
        self,
        skill_name: str,
        script_relative_path: str,
        args: list[str] | None = None,
        input_text: str | None = None,
    ) -> RunScriptResponse:
        try:
            # 复用服务端同一个请求模型做本地校验（比如 input_text 的 64KB 上限），
            # 能在发请求前就失败的不要等到 422。
            payload = RunScriptRequest(
                script_relative_path=script_relative_path, args=args or [], input_text=input_text
            ).model_dump()
        except ValidationError as error:
            raise SkillServiceError(str(error)) from error
        data = await self._request("POST", f"/skills/{skill_name}/run-script", json=payload)
        return RunScriptResponse.model_validate(data)

    async def _request(self, method: str, path: str, **kwargs: object) -> dict:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", **kwargs)
        except httpx.HTTPError as error:
            raise SkillServiceError(f"Skill service is unreachable: {error}") from error
        if response.status_code >= 400:
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
            raise SkillServiceError(str(detail or response.text))
        return response.json()
