"""OAuth 子集专用异常——独立于 `MCPConnectionError` 继承树（授权失败不是连接失败，语义不同）。"""


class OAuthError(Exception):
    pass


class OAuthIssuerMismatchError(OAuthError):
    """发现响应里的 `issuer` 和请求的服务器 URL 不匹配。"""


class OAuthInsecureEndpointError(OAuthError):
    """元数据里的某个 URL 字段使用了不安全的 scheme（javascript:/data:/vbscript: 等）。"""


class OAuthRegistrationError(OAuthError):
    """动态客户端注册失败。"""


class MCPOAuthAuthorizationRequiredError(OAuthError):
    """本地没有可用凭据，调用方需要先走一遍授权流程（展示 authorization_url 给用户）。"""

    def __init__(self, message: str, authorization_url: str) -> None:
        super().__init__(message)
        self.authorization_url = authorization_url
