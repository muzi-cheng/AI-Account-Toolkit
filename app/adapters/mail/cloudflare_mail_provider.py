import random
import string

from curl_cffi import requests


class CloudflareMailProvider:
    """Cloudflare 域名邮箱适配器。"""

    def __init__(self, api_base="", domain="", jwt_token="", proxies=None):
        self.api_base = api_base.strip("/")
        self.domain = domain.strip("@")
        self.proxies = proxies
        self.jwt_token = (jwt_token or "").strip()

    def create_email(self):
        local = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email = f"{local}@{self.domain}"
        return email, email

    def fetch_first_email(self, email):
        """适配 /api/emails 接口，返回首封邮件可解析文本。"""
        try:
            if not self.jwt_token:
                print("[Debug] jwt_token 为空，无法拉取 Cloudflare 邮件")
                return None

            url = f"{self.api_base}/api/emails?mailbox={email}"
            headers = {
                "Authorization": f"Bearer {self.jwt_token}",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }

            res = requests.get(
                url,
                headers=headers,
                timeout=15,
                impersonate="chrome",
                proxies=self.proxies,
            )

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and data:
                    msg = data[0]
                    subject = msg.get("subject", "")
                    preview = msg.get("preview", "")
                    print(f"[Debug] 抓取到邮件主题: {subject}")
                    return f"{subject}\n{preview}"

            return None
        except Exception as e:
            print(f"[Debug] 请求异常: {e}")
            return None
