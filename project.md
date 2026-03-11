# Tigerclaw 项目架构与实现原理

## 项目概述

Tigerclaw 是一个轻量级的 Python AI 助手框架，是 OpenClaw 的 Python 版本实现。它的核心特点是：

- **超轻量**：核心代码仅数千行，比 Clawdbot 小 99%
- **研究友好**：代码清晰易读，便于理解、修改和扩展
- **快速高效**：最小化的占用空间，启动快速，资源占用低
- **易于使用**：一键部署即可使用

## 核心架构

### 1. 整体架构设计

Tigerclaw 采用模块化的分层架构，主要包含以下核心模块：

```
tigerclaw/
├── agent/          # Agent 核心逻辑
├── channels/       # 聊天平台集成
├── bus/            # 消息总线
├── providers/      # LLM 提供商
├── session/        # 会话管理
├── config/         # 配置管理
├── cron/           # 定时任务
├── heartbeat/      # 心跳服务
├── skills/         # 技能系统
└── cli/            # 命令行接口
```

### 2. 消息流转架构

Tigerclaw 使用**消息总线（Message Bus）**模式实现解耦的消息路由：

```
[Chat Channels] → [Inbound Queue] → [Agent Loop] → [Outbound Queue] → [Chat Channels]
```

#### 消息总线实现 (`bus/queue.py`)

```python
class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
```

- **Inbound Queue**: 接收来自各个聊天平台的消息
- **Outbound Queue**: 分发 Agent 的响应到对应的聊天平台
- 使用 asyncio.Queue 实现异步非阻塞的消息传递

### 3. Agent 核心循环 (`agent/loop.py`)

Agent 的核心是一个事件驱动的循环处理系统：

```python
class AgentLoop:
    async def _run_agent_loop(self, session, user_message, media, channel, chat_id):
        # 1. 构建上下文（系统提示词 + 历史消息 + 当前消息）
        messages = self.context.build_messages(...)
        
        # 2. 调用 LLM
        response = await self.provider.chat(messages, tools=self.registry.get_definitions())
        
        # 3. 处理工具调用
        if response.has_tool_calls:
            for tool_call in response.tool_calls:
                result = await self.registry.execute(tool_call.name, tool_call.arguments)
                # 将工具结果添加到消息历史
                messages = self.context.add_tool_result(...)
            # 继续循环，让 LLM 处理工具结果
            continue
        
        # 4. 返回最终响应
        return response.content
```

**关键特性**：
- 支持多轮工具调用循环
- 自动管理消息历史
- 支持流式响应和进度通知
- 集成记忆整合机制

## 核心组件详解

### 1. 上下文构建器 (`agent/context.py`)

负责构建发送给 LLM 的完整上下文：

```python
class ContextBuilder:
    def build_system_prompt(self, skill_names):
        # 组装系统提示词
        parts = [
            self._get_identity(),           # 身份和运行时信息
            self._load_bootstrap_files(),   # AGENTS.md, SOUL.md, USER.md, TOOLS.md
            self.memory.get_memory_context(), # 长期记忆
            self.skills.load_skills_for_context(skill_names), # 技能
        ]
        return "\n\n---\n\n".join(parts)
```

**上下文组成**：
1. **身份信息**：运行时环境、工作空间路径、平台策略
2. **引导文件**：从工作空间加载的配置文件
3. **记忆系统**：长期记忆（MEMORY.md）和历史日志（HISTORY.md）
4. **技能系统**：已激活的技能和可用技能列表

### 2. 工具系统

#### 工具注册表 (`agent/tools/registry.py`)

```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool):
        self._tools[tool.name] = tool
    
    async def execute(self, name: str, params: dict):
        tool = self._tools.get(name)
        # 参数类型转换和验证
        params = tool.cast_params(params)
        errors = tool.validate_params(params)
        # 执行工具
        return await tool.execute(**params)
```

#### 内置工具类型

- **文件系统工具** (`tools/filesystem.py`): 读写文件、列出目录
- **Shell 工具** (`tools/shell.py`): 执行命令
- **Web 工具** (`tools/web.py`): 网页搜索和抓取
- **消息工具** (`tools/message.py`): 发送消息到聊天频道
- **Cron 工具** (`tools/cron.py`): 管理定时任务
- **MCP 工具** (`tools/mcp.py`): Model Context Protocol 集成

#### MCP 集成 (`agent/tools/mcp.py`)

支持通过 MCP 协议连接外部工具服务器：

```python
class MCPToolWrapper(Tool):
    async def execute(self, **kwargs):
        result = await self._session.call_tool(
            self._original_name, 
            arguments=kwargs
        )
        # 处理结果
        return result
```

**支持的传输模式**：
- **Stdio**: 本地进程（通过 npx/uvx）
- **HTTP**: 远程端点（SSE 或 streamableHttp）

### 3. LLM 提供商系统

#### Provider 基类 (`providers/base.py`)

```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        pass
```

#### Provider 注册表 (`providers/registry.py`)

使用 `ProviderSpec` 定义提供商规范：

```python
@dataclass
class ProviderSpec:
    name: str                    # 配置字段名
    keywords: tuple[str, ...]    # 模型名关键词
    env_key: str                 # 环境变量名
    display_name: str            # 显示名称
    litellm_prefix: str          # LiteLLM 前缀
    skip_prefixes: tuple[str, ...] # 跳过前缀
```

**支持的提供商**：
- OpenRouter, Anthropic, OpenAI, Azure OpenAI
- DeepSeek, Groq, Gemini, MiniMax
- 国内提供商：智谱、月之暗面、火山引擎、阿里云等
- 自定义 OpenAI 兼容端点

### 4. 会话管理 (`session/manager.py`)

```python
@dataclass
class Session:
    key: str  # channel:chat_id
    messages: list[dict]
    created_at: datetime
    updated_at: datetime
    last_consolidated: int  # 已整合的消息数量
    
    def get_history(self, max_messages: int = 500):
        # 返回未整合的消息，用于 LLM 输入
        unconsolidated = self.messages[self.last_consolidated:]
        return unconsolidated[-max_messages:]
```

**会话特性**：
- 以 JSONL 格式持久化存储
- 支持消息追加（append-only）以优化 LLM 缓存
- 自动迁移旧版会话文件
- 支持会话元数据和整合状态

### 5. 记忆系统 (`agent/memory.py`)

采用**两层记忆架构**：

```python
class MemoryStore:
    def __init__(self, workspace: Path):
        self.memory_file = workspace / "memory" / "MEMORY.md"  # 长期记忆
        self.history_file = workspace / "memory" / "HISTORY.md"  # 历史日志
```

#### 记忆整合流程

```python
async def consolidate(self, session, provider, model):
    # 1. 获取待整合的消息
    old_messages = session.messages[session.last_consolidated:-keep_count]
    
    # 2. 调用 LLM 进行整合（使用虚拟工具调用）
    response = await provider.chat(
        messages=[...],
        tools=_SAVE_MEMORY_TOOL,  # save_memory 工具
    )
    
    # 3. 保存整合结果
    if response.has_tool_calls:
        args = response.tool_calls[0].arguments
        self.append_history(args["history_entry"])  # 添加到历史日志
        self.write_long_term(args["memory_update"])  # 更新长期记忆
```

**记忆整合触发条件**：
- 消息数量超过阈值（默认 50 条）
- 手动触发整合
- 会话结束时整合所有消息

### 6. 技能系统 (`agent/skills.py`)

```python
class SkillsLoader:
    def __init__(self, workspace: Path, builtin_skills_dir: Path):
        self.workspace_skills = workspace / "skills"  # 用户技能
        self.builtin_skills = builtin_skills_dir      # 内置技能
```

**技能特性**：
- 技能以 Markdown 文件（SKILL.md）形式存储
- 支持 YAML frontmatter 元数据
- 支持依赖检查（bins, env）
- 支持 always 标记（自动加载）
- 渐进式加载：先显示摘要，需要时再读取完整内容

**内置技能**：
- GitHub 集成
- 天气查询
- Tmux 管理
- Cron 任务
- 记忆管理
- 技能创建器

### 7. 聊天频道系统

#### 基础频道接口 (`channels/base.py`)

```python
class BaseChannel(ABC):
    @abstractmethod
    async def start(self):
        """启动频道，监听消息"""
        pass
    
    @abstractmethod
    async def send(self, msg: OutboundMessage):
        """发送消息"""
        pass
    
    async def _handle_message(self, sender_id, chat_id, content, media):
        # 权限检查
        if not self.is_allowed(sender_id):
            return
        # 发布到消息总线
        await self.bus.publish_inbound(InboundMessage(...))
```

#### 频道管理器 (`channels/manager.py`)

```python
class ChannelManager:
    def __init__(self, config: Config, bus: MessageBus):
        self._init_channels()  # 根据配置初始化频道
    
    async def start_all(self):
        # 启动所有频道
        # 启动出站消息分发器
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
```

**支持的频道**：
- Telegram（推荐）
- Discord
- WhatsApp
- Feishu（飞书）
- DingTalk（钉钉）
- Slack
- QQ
- Matrix
- Email
- Mochat

### 8. 定时任务系统 (`cron/service.py`)

```python
class CronService:
    def __init__(self, workspace, provider, model):
        self.store_file = workspace / "cron" / "jobs.json"
    
    async def _on_timer(self):
        # 检查到期任务
        for job in self._get_due_jobs():
            await self._execute_job(job)
    
    async def _execute_job(self, job: CronJob):
        # 通过 Agent 执行任务
        response = await self.on_execute(job.prompt)
        # 发送结果通知
        if self.on_notify:
            await self.on_notify(response)
```

**Cron 特性**：
- 支持标准 cron 表达式
- 持久化存储（JSON）
- 支持启用/禁用
- 支持手动触发
- 集成 Agent 执行

### 9. 心跳服务 (`heartbeat/service.py`)

定期唤醒 Agent 检查待办任务：

```python
class HeartbeatService:
    async def _tick(self):
        # 1. 读取 HEARTBEAT.md
        content = self._read_heartbeat_file()
        
        # 2. 询问 LLM 是否有任务（使用虚拟工具调用）
        action, tasks = await self._decide(content)
        
        # 3. 如果有任务，执行并通知
        if action == "run" and self.on_execute:
            response = await self.on_execute(tasks)
            await self.on_notify(response)
```

**心跳特性**：
- 默认每 30 分钟检查一次
- 使用虚拟工具调用避免文本解析
- 支持手动触发
- 自动发送结果到最近活跃的聊天频道

## 配置系统

### 配置架构 (`config/schema.py`)

使用 Pydantic 进行配置验证：

```python
class Config(BaseModel):
    agents: AgentsConfig
    channels: ChannelsConfig
    providers: ProvidersConfig
    tools: ToolsConfig
    gateway: GatewayConfig
    heartbeat: HeartbeatConfig
    web: WebSearchConfig
```

### 配置加载 (`config/loader.py`)

支持多种配置来源：
1. 默认配置
2. 用户配置文件（`~/.tigerclaw/config.json`）
3. 工作空间配置
4. 环境变量

### 多实例支持

通过 `--config` 参数支持运行多个独立实例：

```bash
tigerclaw gateway --config ~/.tigerclaw-telegram/config.json
tigerclaw gateway --config ~/.tigerclaw-discord/config.json
```

每个实例拥有独立的：
- 配置文件
- 工作空间
- 会话数据
- Cron 任务
- 媒体文件

## 命令行接口 (`cli/commands.py`)

### 主要命令

```python
@app.command()
def onboard():
    """初始化配置和工作空间"""

@app.command()
def agent():
    """启动交互式 Agent"""

@app.command()
def gateway():
    """启动网关服务（连接聊天频道）"""

@app.command()
def status():
    """显示系统状态"""
```

### Gateway 模式

Gateway 是 Tigerclaw 的服务器模式，负责：
1. 启动所有启用的聊天频道
2. 启动 Agent 循环处理消息
3. 启动心跳服务
4. 启动 Cron 服务

```python
async def gateway_main():
    # 1. 初始化消息总线
    bus = MessageBus()
    
    # 2. 启动频道管理器
    channel_manager = ChannelManager(config, bus)
    await channel_manager.start_all()
    
    # 3. 启动 Agent 循环
    agent_loop = AgentLoop(config, bus)
    await agent_loop.run()
    
    # 4. 启动心跳和 Cron 服务
    await heartbeat.start()
    await cron.start()
```

## 数据流示例

### 完整的消息处理流程

```
1. 用户在 Telegram 发送消息
   ↓
2. TelegramChannel 接收消息
   ↓
3. 发布到 MessageBus.inbound
   ↓
4. AgentLoop 从队列消费消息
   ↓
5. 构建上下文（系统提示词 + 历史 + 当前消息）
   ↓
6. 调用 LLM Provider
   ↓
7. LLM 返回工具调用
   ↓
8. ToolRegistry 执行工具
   ↓
9. 将工具结果添加到消息历史
   ↓
10. 再次调用 LLM 处理工具结果
   ↓
11. LLM 返回最终响应
   ↓
12. 发布到 MessageBus.outbound
   ↓
13. ChannelManager 分发到 TelegramChannel
   ↓
14. 发送消息给用户
```

## 安全特性

### 权限控制

```python
def is_allowed(self, sender_id: str) -> bool:
    allow_list = getattr(self.config, "allow_from", [])
    if not allow_list:
        return False  # 空列表拒绝所有
    if "*" in allow_list:
        return True   # "*" 允许所有
    return str(sender_id) in allow_list
```

### 工作空间沙箱

```python
# 配置选项
tools.restrictToWorkspace = true  # 限制所有工具在工作空间内操作
```

## 扩展性设计

### 1. 添加新的 LLM Provider

只需两步：

1. 在 `providers/registry.py` 添加 `ProviderSpec`
2. 在 `config/schema.py` 添加配置字段

### 2. 添加新的聊天频道

1. 继承 `BaseChannel` 实现接口
2. 在 `ChannelManager._init_channels()` 添加初始化逻辑

### 3. 添加新的工具

1. 继承 `Tool` 基类
2. 实现 `execute()` 方法
3. 在 `AgentLoop._register_default_tools()` 注册

### 4. 添加新的技能

在工作空间创建 `skills/<skill-name>/SKILL.md` 文件

## 性能优化

### 1. 消息历史管理

- 使用 append-only 模式优化 LLM 缓存
- 定期整合旧消息到记忆文件
- 限制发送给 LLM 的消息数量（默认 500 条）

### 2. 异步架构

- 全面使用 asyncio 实现非阻塞 I/O
- 消息总线解耦组件
- 并发处理多个频道

### 3. 工具超时控制

```python
# MCP 工具超时配置
toolTimeout: 30  # 默认 30 秒
```

## 部署方式

### 1. 本地安装

```bash
pip install -e .
tigerclaw onboard
tigerclaw agent
```

### 2. Docker 部署

```bash
docker compose up -d tigerclaw-gateway
```

### 3. 多实例部署

```bash
# 不同频道使用不同实例
tigerclaw gateway --config ~/.tigerclaw-telegram/config.json
tigerclaw gateway --config ~/.tigerclaw-discord/config.json --port 18791
```

## 总结

Tigerclaw 的设计哲学是**简单、模块化、可扩展**：

1. **消息总线架构**：解耦聊天频道和 Agent 核心
2. **工具系统**：统一的工具注册和执行机制，支持 MCP 扩展
3. **记忆系统**：两层记忆架构，平衡性能和上下文
4. **技能系统**：渐进式加载，按需激活
5. **Provider 抽象**：统一的 LLM 接口，支持多种提供商
6. **异步优先**：全面使用 asyncio 提升性能
7. **配置驱动**：通过配置文件控制所有行为
8. **多实例支持**：轻松部署多个独立实例

这种架构使得 Tigerclaw 既轻量又强大，适合研究、开发和生产环境使用。
