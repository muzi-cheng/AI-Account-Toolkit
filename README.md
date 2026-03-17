# ChatGPT 批量自动注册工具（工程化版）

> 使用 Cloudflare 域名邮箱，并发自动注册 ChatGPT 账号。
> 当前配置体系：`静态默认(app/config/config.py) + 用户配置(config.py) + 运行状态(run_state.json)`。

## 功能

- 📨 自动创建 Cloudflare 域名邮箱
- 📥 自动获取 OTP 验证码
- ⚡ 支持并发注册多个账号
- 🔄 自动处理 OAuth 登录
- ☁️ 支持代理配置
- 📤 支持上传账号到 cliproxyapi / Sub2API 面板

## 环境

```bash
pip install -r requirements.txt
```

或最小安装：

```bash
pip install curl_cffi
```

## 配置

### 1) 静态默认配置（代码内）

- 文件：`app/config/config.py`
- 用途：不常变化的默认值、路径常量、运行状态默认结构。

### 2) 用户配置（你需要修改）

- 模板文件：`config.py.example`
- 实际生效文件：`config.py`
- 用途：覆盖默认值（建议仅保留你真正需要改的字段）

先复制示例文件：

```bash
cp config.py.example config.py
```

然后再编辑 `config.py` 填写你的真实配置（token/key/域名等）。

```python
# 基本运行参数
total_accounts = 1
max_workers = 1

# 代理池（仅注册流程使用）
proxy_pool = [
  "http://127.0.0.1:10001",
  "http://127.0.0.1:10002",
]

# Cloudflare 私有邮件服务配置
cloudflare_api_base = "https://your-mail-service.example.com"
cloudflare_domain = "example.com"
cloudflare_jwt_token = "请填写你的 Cloudflare JWT Token"

# 上传目标
upload_targets = ["cliproxyapi", "sub2api"]

# CliProxyAPI
cliproxyapi_api_base_url = "https://your-cliproxyapi.example.com"
cliproxyapi_api_token = "请填写你的 CliProxyAPI Bearer Token"

# Sub2API
sub2api_url = "https://your-sub2api.example.com"
sub2api_auth_mode = "x-api-key"
sub2api_api_key = "请填写你的 Sub2API x-api-key"
sub2api_group_ids = [8, 6]
```

| 配置项 | 说明 |
|--------|------|
| total_accounts | 注册账号数量 |
| max_workers | 注册并发数 |
| post_account_wait_min_seconds | 单账号完成后的最小随机等待秒数（默认 20） |
| post_account_wait_max_seconds | 单账号完成后的最大随机等待秒数（默认 60） |
| cloudflare_api_base | Cloudflare 邮件 API 地址 |
| cloudflare_domain | 邮箱域名 |
| cloudflare_jwt_token | Cloudflare JWT Token |
| proxy_pool | 注册代理池（可选） |
| enable_oauth | 启用 OAuth 登录 |
| oauth_required | OAuth 失败是否视为注册失败 |

### 3) 运行状态文件（程序自动写入）

- 文件：`run_state.json`
- 用途：记录最近一次运行状态（started/finished/success/fail/耗时等）

## Sub2API 面板集成

注册完成后，可以自动上传账号到 Sub2API：

| 配置项 | 说明 | 参考 |
|--------|------|------|
| sub2api_url | Sub2API 地址 | 你的 Sub2API 服务 |
| sub2api_import_path | 导入接口路径 | 默认 `/api/v1/admin/accounts/data` |
| sub2api_auth_mode | 鉴权模式：`bearer` / `cookie` / `x-api-key` | 默认 `bearer` |
| sub2api_token | Bearer Token（bearer 模式） | 可选 |
| sub2api_cookie | Cookie（cookie 模式） | 可选 |
| sub2api_api_key | API Key（x-api-key 模式） | 可选 |

## 使用

```bash
python main.py
```

程序会直接使用配置中的 `total_accounts` 和 `max_workers`，不再交互式输入。

## 并发与退出行为

- 每个账号注册完成后，会按 `post_account_wait_min_seconds ~ post_account_wait_max_seconds` 做随机等待（支持配置，默认 `20~60s`）。
- 当成功注册数量达到 `total_accounts` 目标后：
  - 不再提交新的注册任务；
  - 已在执行中的任务会继续跑完；
  - 处于“账号完成后随机等待”阶段的任务会提前结束等待；
  - 全部在途任务结束后，主程序立即退出。

## 输出

当前只保留服务上传相关产物，不再生成以下历史文件：

- `codex_tokens/ak.txt`
- `codex_tokens/rk.txt`
- `codex_tokens/registered_accounts.txt`
- `codex_tokens/registered_accounts_details.jsonl`

## 目录结构

```
chatgpt_register/
├── main.py                 # 主程序入口
├── config.py.example       # 用户配置示例（先复制为 config.py）
├── config.py               # 用户本地配置（已被 .gitignore 忽略）
├── run_state.json          # 运行状态（程序自动更新）
├── README.md               # 本文档
├── app/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── config.py       # 静态默认配置与常量
│   │   └── settings.py     # 配置加载 + 运行状态读写
│   ├── adapters/
│   │   ├── __init__.py
│   │   └── mail/
│   │       ├── __init__.py
│   │       └── cloudflare_mail_provider.py # Cloudflare 邮件适配器
│   └── utils/
│       ├── __init__.py
│       └── booleans.py     # 通用布尔转换工具
├── codex_tokens/
│   ├── local/
│   ├── cliproxyapi/
│   └── sub2api/
└── ...
```

> 当前已完成工程化重命名与清理：
> - `app/config.py` → `app/config/settings.py`
> - `app/mail/cloudflare_email_service.py` → `app/adapters/mail/cloudflare_mail_provider.py`
> - 删除历史冗余脚本，统一入口为 `main.py`

## 注意事项

- 需要有效的代理才能注册成功
- 需在 `config.py` 中正确设置 `cloudflare_jwt_token`
- 建议使用代理避免 IP 被封
- 使用 Sub2API 需要先部署并配置对应鉴权信息
