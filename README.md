## 注：该项目完全vibe coding，不保证质量

# AI课堂助手 (AIAnswer)

在上课过程中实时监听老师讲课，自动检测疑似提问的语句，并调用 AI 生成口语化、简短的回答，辅助你快速组织思路。

---

## 注: 使用时需要将config/user.json.example后的.example去掉，改名为user.json再填写密钥等内容
## 若不知道在哪里获得讯飞相关功能，可以查看"使用说明.md"的 5.首次配置向导 

## 功能特点

- **实时语音转文字**：支持讯飞 WebSocket 流式识别，也支持直接对接兼容 `/audio/transcriptions` 的语音转写 API。
- **智能提问检测**：内置 16 个常见提问触发词（如"问个问题""请一位同学""怎么看"），命中即触发 AI 回答。
- **流式 AI 回答**：支持 OpenAI 兼容格式的任意大模型 API，回答边生成边显示，无需等待。
- **轻量省电**：语音识别与 AI 推理均在云端完成，本地只做音频采集与界面展示，适配笔记本离电场景。
- **API Key 自主管理**：讯飞 ASR Key 与 LLM API Key 均由用户自行填写，不经过第三方中转，隐私可控。

---

## 环境要求

- **操作系统**：Linux / Windows / macOS（有图形界面）
- **Python**：3.10 或更高版本
- **网络**：上课环境需能访问互联网
- **硬件**：麦克风（笔记本自带或外接均可）

---

## 环境准备

本项目需要 Python 3.10+。推荐使用**虚拟环境**隔离依赖，避免与系统 Python 包冲突。

> **Linux 用户注意**：若安装 `pyaudio` 报错，请先安装系统依赖：
> ```bash
> # Ubuntu/Debian
> sudo apt-get install python3-tk portaudio19-dev
>
> # Fedora
> sudo dnf install python3-tkinter portaudio-devel
> ```

### 方式一：标准 venv（推荐大多数用户）

```bash
cd /path/to/AIAnswer

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境（Linux/macOS）
source venv/bin/activate
# 激活虚拟环境（Windows CMD）
# venv\Scripts\activate.bat
# 激活虚拟环境（Windows PowerShell）
# venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

以后每次运行前，只需先激活虚拟环境：
```bash
source venv/bin/activate   # Linux/macOS
python main.py
```

### 方式二：uv（推荐追求速度的用户）

[uv](https://github.com/astral-sh/uv) 是 Astral 出品的高性能 Python 包管理器，比 pip 快 10~100 倍，且内置虚拟环境管理。

**安装 uv**：
```bash
# 方式 A：通过 pip（若你已有 Python）
pip install uv

# 方式 B：独立安装（不依赖 Python，推荐）
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**创建环境并安装依赖**：
```bash
cd /path/to/AIAnswer

# uv 会自动创建 .venv 并安装依赖
uv venv
uv pip install -r requirements.txt
```

**以后运行**：
```bash
# uv 会自动识别 .venv，无需手动激活
uv run python main.py
```

> 💡 **uv 优势**：`uv run` 会自动使用 `.venv` 中的 Python，无需记忆 `source activate` 命令，非常适合新手。

---

## 安装步骤（快速版）

如果你已经搭建好虚拟环境，只需：

```bash
cd /path/to/AIAnswer
# 确保虚拟环境已激活（venv 用户）
pip install -r requirements.txt
```

然后运行程序：
```bash
# venv 用户（确保已激活）
python main.py

# uv 用户（无需手动激活）
uv run python main.py
```

---

## 配置指南（首次使用必看）

点击界面右上角「**设置**」按钮，填写以下信息后保存。

### ① 讯飞语音听写 (ASR)

用于将老师的讲课语音实时转成文字。

1. 打开 [讯飞开放平台](https://www.xfyun.cn/)
2. 注册/登录账号
3. 进入「控制台」→「创建应用」
4. 在应用详情页找到：
   - **APPID**
   - **APIKey**
   - **APISecret**
5. 在「语音识别」→「语音听写（流式版）」中确认已开通服务（新用户有免费额度）
6. 将三项信息填入软件设置界面

### ② 兼容音频转写 API 的 ASR

如果你不想接讯飞，也**不需要自己额外搭一个 ASR 服务**。项目内已经内置了一个 HTTP 分段转写客户端，只要目标平台支持 OpenAI 风格的 `/v1/audio/transcriptions` 接口即可。

填写项：
- **API Base**：例如 `https://api.openai.com/v1`
- **API Key**：服务商提供的密钥；如果你的自建服务未启用鉴权，可留空
- **Model**：例如 `whisper-1`

注意：这里要求目标服务本身支持音频转写接口；如果一个平台只提供聊天模型 `/chat/completions`，那它不能直接拿来做 ASR。

### ③ 大语言模型 (LLM)

用于生成提问的回答。支持任何 **OpenAI 兼容格式** 的 API。

**推荐方案（国内用户）**：

| 服务商 | API Base | 说明 |
|--------|----------|------|
| DeepSeek | `https://api.deepseek.com/v1` | 便宜、速度快 |
| 阿里通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 国内稳定 |
| OpenAI | `https://api.openai.com/v1` | 需翻墙 |

填写项：
- **API Base**：服务商的 API 地址（见上表）
- **API Key**：从对应平台获取的密钥
- **Model**：模型名称，如 `deepseek-chat`、`qwen-turbo`、`gpt-4o-mini`

> 💡 **省钱建议**：课堂回答不需要太强模型，使用 `deepseek-chat` 或 `gpt-4o-mini` 级别即可，费用极低。

### ③ 提问触发词（可选）

默认已内置常见提问用语。如果你有特定老师的口头禅（如"考考你们"），可以每行添加一个。

---

## 使用方法

```bash
python main.py
```

### 界面说明

```
+--------------------------------------------------+
|  AI课堂助手                           [设置] [开始]|
+--------------------------------------------------+
|  实时字幕              |  AI 回答                  |
|  +------------------+  |  +--------------------+  |
|  | 老师：下面我来... |  |  | [14:32] 这个问题...|  |
|  | 老师：请一位同... |  |  |         简单来说...|  |
|  +------------------+  |  +--------------------+  |
+--------------------------------------------------+
|  状态：运行中 | 正在监听...                        |
+--------------------------------------------------+
```

| 区域 | 说明 |
|------|------|
| **实时字幕** | 显示语音识别结果，随老师说话实时滚动。 |
| **AI 回答** | 当检测到提问时，自动显示 AI 生成的简短回答，带时间戳。 |
| **状态栏** | 显示当前运行状态、连接情况。 |

### 操作流程

1. 首次打开 → 点击「**设置**」→ 填写讯飞 ASR 和 LLM 配置 → 保存
2. 回到主界面 → 点击「**开始听课**」
3. 对着麦克风说话（或上课正常听讲）
4. 当老师说出口头禅/提问语句时，右侧自动出现 AI 回答
5. 下课后点击「**停止**」

---

## 常见问题

### Q1：点击开始后提示"无法连接讯飞 ASR"
- 检查 APPID / APIKey / APISecret 是否填写正确（不要有多余空格）
- 检查网络是否能访问 `wss://iat-api.xfyun.cn`
- 确认讯飞控制台中已开通「语音听写（流式版）」服务

### Q2：有字幕但不触发 AI 回答
- 确认触发词列表包含老师实际使用的表达
- 检查 LLM 的 API Key 和 API Base 是否填写正确
- 查看状态栏是否有 LLM 错误提示（如 401 代表 Key 无效）

### Q3：AI 回答很慢或超时
- 国内用户建议使用 DeepSeek / 阿里通义等国内 API，避免跨国网络延迟
- 检查上课环境 WiFi 是否稳定
- 可在设置中换用更轻量的模型（如 `gpt-4o-mini`）

### Q4：字幕重复或跳动
- 这是流式 ASR 正常行为。软件已内置 diff 逻辑，会自动去重和修正。
- 若跳动严重，检查麦克风是否有杂音干扰，或尝试外接USB麦克风。

### Q5：软件支持保存课堂记录吗？
- 当前 MVP 版本暂未内置保存功能。可复制左侧字幕区内容手动保存。
- 后续版本计划支持一键导出 Markdown 笔记。

---

## 项目结构

```
AIAnswer/
├── main.py                  # 程序入口
├── requirements.txt         # Python 依赖
├── README.md                # 本文档
├── config/
│   ├── default.json         # 默认配置模板
│   └── user.json            # 用户实际配置（首次保存后生成）
├── src/
│   ├── audio/
│   │   └── capture.py       # 麦克风音频采集
│   ├── asr/
│   │   └── xunfei_ws.py     # 讯飞流式语音识别
│   ├── detector/
│   │   ├── buffer.py        # 文本滑动窗口
│   │   └── trigger.py       # 提问检测器
│   ├── llm/
│   │   └── client.py        # LLM SSE 流式客户端
│   ├── ui/
│   │   └── app.py           # tkinter 界面
│   ├── config/
│   │   └── manager.py       # 配置读写管理
│   └── utils/
│       └── logger.py        # 日志工具
└── docs/                    # 开发文档（架构/模块设计/开发计划）
```

---

## 隐私与安全

- **语音数据**：实时发送至讯飞开放平台进行识别，不在本地长期存储。
- **API Key**：仅保存在本地 `config/user.json` 中，不会上传至任何第三方服务器。
- **AI 上下文**：每次提问的上下文仅在内存中暂存，回答完成后即释放。

---

## 技术栈

- Python 3.10+
- tkinter（轻量 GUI，系统自带）
- pyaudio（音频采集）
- websockets（讯飞 ASR WebSocket 连接）
- aiohttp（LLM SSE 流式请求）
- asyncio（单线程并发核心）

---

## 许可

本项目仅供学习交流使用。使用第三方 API（讯飞、DeepSeek、OpenAI 等）时，请遵守对应平台的服务条款。
