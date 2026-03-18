# AI-Account-Toolkit

面向 OpenAI / ChatGPT 账号批量注册、Token 管理、账号巡检与持续保号的工程化工具集。

当前项目已经完成第一阶段工程化重构：主入口开始接入 `CLI + Bootstrap + Application Use Cases + Infrastructure` 分层，后续会继续把根目录 `main.py` 中的历史逻辑逐步下沉。

## 核心能力

- 批量注册 ChatGPT / OpenAI 账号
- 使用 Cloudflare Mail / freemail 风格接口生成域名邮箱并拉取验证码
- 支持 OAuth 登录并保存 token 产物
- 支持代理池并发注册
- 支持上传账号到 `CliProxyAPI` / `Sub2API`
- 支持本地账号巡检，清理 `401 + deactivated` 失效账号
- 支持 `maintain` 持续保号，自动补足目标账号数量

---

## 项目结构

```text
AI-Account-Toolkit/
├── main.py                          # 当前兼容主入口，已接入新 CLI / container / use case
├── README.md
├── config.py.example                # 用户配置模板
├── requirements.txt
├── run_state.json                   # 运行状态文件（运行后生成/更新）
├── app/
│   ├── cli/
│   │   └── main.py                  # CLI 参数定义
│   ├── bootstrap/
│   │   └── container.py             # 依赖装配
│   ├── application/
│   │   └── use_cases/
│   │       └── token_maintenance.py # 巡检 / 保号 use case
│   ├── domain/
│   │   ├── models/                  # 领域模型
│   │   └── ports/                   # 端口接口定义
│   ├── infrastructure/
│   │   ├── mail/
│   │   │   └── cloudflare_mail_provider.py
│   │   └── persistence/
│   │       └── json_run_state_repository.py
│   ├── config/
│   │   ├── config.py                # 静态默认配置
│   │   ├── loader.py                # 配置加载
│   │   ├── schema.py                # 配置 / 状态 schema 导出
│   │   └── settings.py              # 兼容层配置读写
│   └── utils/
│       └── booleans.py
└── codex_tokens/
    ├── local/
    ├── cliproxyapi/
    └── sub2api/
```

---

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

最小依赖场景也至少需要：

```bash
pip install curl_cffi
```

### 2. 准备配置文件

把示例配置复制为实际配置：

```bash
copy config.py.example config.py
```

然后编辑 `config.py`。

---

## 配置说明

当前配置体系分为三层：

1. **静态默认配置**：`app/config/config.py`
2. **用户配置覆盖**：`config.py`
3. **运行状态**：`run_state.json`

### 常用配置项

```python
# 基础运行参数
total_accounts = 30
max_workers = 1

# 注册代理池
proxy_pool = [
    "http://127.0.0.1:10001",
    "http://127.0.0.1:10002",
]

# Cloudflare Mail / freemail
cloudflare_api_base = "https://your-freemail.example.com"
cloudflare_domain = "example.com"
cloudflare_jwt_token = "请填写你的 Bearer Token"
cloudflare_poll_attempts = 3
cloudflare_poll_interval = 5

# 上传目标
upload_targets = ["cliproxyapi", "sub2api"]

# 保号模式
maintain_enabled = True
maintain_check_interval_seconds = 1800
```

### 关键配置表

| 配置项 | 说明 |
|---|---|
| `total_accounts` | 目标账号数量 |
| `max_workers` | 最大并发数 |
| `proxy_pool` | 注册与巡检可复用的代理池 |
| `cloudflare_api_base` | Cloudflare Mail / freemail 服务地址 |
| `cloudflare_domain` | 邮箱域名 |
| `cloudflare_jwt_token` | freemail API Bearer Token |
| `cloudflare_poll_attempts` | 拉取验证码的最大轮询次数 |
| `cloudflare_poll_interval` | 每轮拉取间隔秒数 |
| `upload_targets` | 上传目标列表：`cliproxyapi` / `sub2api` |
| `token_check_input_file` | 本地账号文件，默认 `codex_tokens/local/accounts.json` |
| `token_check_report_file` | 巡检报告输出文件 |
| `maintain_enabled` | 是否开启持续保号 |
| `maintain_check_interval_seconds` | 保号巡检周期 |
| `maintain_register_retry_limit` | 单轮补号重试上限，`0` 表示不限制 |

---

## Cloudflare Mail / freemail 配置指南

本项目当前对接的是 **freemail 风格接口**。推荐使用这个开源项目先搭建邮件服务：

- 开源地址：`https://github.com/idinging/freemail`

### 1. 先部署 freemail

请先参考 freemail 项目的官方文档完成部署，并确保你已经：

- 在 Cloudflare 中托管了域名
- 正确配置了 Cloudflare Email Routing / 相关邮件能力
- 拿到了 freemail 服务访问地址
- 拿到了 freemail 的 Bearer Token / JWT Token

### 2. 在本项目中填写对应配置

```python
cloudflare_api_base = "https://your-freemail.example.com"
cloudflare_domain = "example.com"
cloudflare_jwt_token = "your_freemail_bearer_token"
cloudflare_poll_attempts = 3
cloudflare_poll_interval = 5
```

### 3. 本项目当前实际依赖的接口形式

根据当前实现：

- 创建邮箱时，本项目会本地生成随机前缀邮箱：`<random>@<cloudflare_domain>`
- 拉取邮件时，会请求：

```http
GET {cloudflare_api_base}/api/emails?mailbox=<email>
Authorization: Bearer <cloudflare_jwt_token>
```

也就是说，你部署的 freemail 服务至少需要兼容这个读取接口。

### 4. 返回数据要求

当前代码会把 `/api/emails` 的响应按 **列表** 处理，并读取首封邮件的：

- `subject`
- `preview`

然后从内容里提取 6 位验证码。

如果你的 freemail 部署做了二次定制，请确保返回结构与当前项目兼容。

### 5. 配置完成后的最小检查

```bash
python main.py --help
python main.py check-tokens --help
python main.py maintain --help
```

如果要跑真实注册，请确保 `cloudflare_jwt_token`、域名、代理都已经配置正确。

---

## 使用方式

### 1. 默认执行批量注册 / 保号主流程

```bash
python main.py
```

程序直接读取 `config.py` 中的 `total_accounts` 和 `max_workers`，不再交互式输入。

### 2. 巡检本地账号

```bash
python main.py check-tokens
```

可指定输入与报告文件：

```bash
python main.py check-tokens --input codex_tokens/local/accounts.json --report codex_tokens/token_check_report.json
```

### 3. 持续保号

```bash
python main.py maintain --interval 1800
```

---

## 巡检与保号逻辑

### `check-tokens`

- 默认读取 `codex_tokens/local/accounts.json`
- 使用 `token_check_url` 检测账号状态
- 复用配置里的 `proxy_pool` 轮询检测
- **仅当响应满足 `HTTP 401` 且内容包含 `deactivated` 时，才执行删除**

删除动作包括：

- 从本地 `accounts.json` 移除账号
- 删除本地 `cliproxyapi/*.json`
- 删除本地 `sub2api/*.json`
- 调用 Sub2API 删除远端账号
- 调用 CliProxyAPI 删除远端文件

### `maintain`

`maintain` 会循环执行：

1. 巡检本地账号
2. 删除已失效账号
3. 计算与 `total_accounts` 的缺口
4. 自动补注册
5. 到达周期后继续下一轮

---

## 产物说明

主要产物目录：`codex_tokens/`

- `local/accounts.json`：本地账号汇总
- `cliproxyapi/*.json`：发送到 CliProxyAPI 前的账号 JSON
- `sub2api/*.json`：发送到 Sub2API 前的账号 payload
- `token_check_report.json`：巡检报告

运行状态文件：

- `run_state.json`

> 说明：代码里仍保留了一些历史产物字段兼容项（如 `output_file` / `ak_file` / `rk_file`），后续会继续清理，但当前主流程已经主要收敛到 `codex_tokens/` 目录。

---

## 与当前工程化重构的关系

本项目正在按 Google 风格常见工程化分层继续演进：

- `CLI`：只负责命令解析
- `Bootstrap`：负责容器装配
- `Application`：负责 use case 编排
- `Domain`：负责模型与端口接口
- `Infrastructure`：负责外部系统接入

目前已完成的重点：

- `check-tokens` 已走新的 `TokenCheckUseCase`
- `maintain` 已走新的 `MaintainAccountsUseCase`
- `container` 已去除对 `main.py` 的反向依赖

后续会继续拆分 `main.py` 中的注册、OAuth、上传与持久化逻辑。

---

## 注意事项

- 真实注册强依赖稳定代理与可用邮箱域名
- 未配置 `cloudflare_jwt_token` 时，真实模式无法拉取验证码邮件
- `check-tokens` 只删除 `401 + deactivated` 账号，其他异常会保留并记录
- 使用 `Sub2API` / `CliProxyAPI` 前，请先确认你的接口地址、鉴权方式、删除路径配置正确
- Windows 终端下若帮助信息出现中文乱码，通常是终端编码问题，不影响程序逻辑
