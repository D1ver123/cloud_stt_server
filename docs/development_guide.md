# xiaozhi-cloud-stt 开发文档

## 1. 代码结构

```text
src/
  cloud_stt_client/
    cli.py
    config.py
    encoding.py
    pipeline.py
    preferences.py
    protocol.py
    audio/
      capture.py
      devices.py
      processing.py
      wav_source.py
  cloud_stt_server/
    app.py
    config.py
    protocol.py
    sessions.py
    adapter/
      text_adapter.py
    asr/
      base.py
      factory.py
      dashscope_realtime.py
    audio/
      decoder.py
      pcm.py
      queue.py
      rolling_buffer.py
    command/
      base.py
      models.py
      rule_parser.py
    vad/
      fsmn_vad.py
tests/
docs/
```

## 2. 客户端实现

### 2.1 CLI

入口文件：

```text
src/cloud_stt_client/cli.py
```

命令：

- `list-devices`：列出输入设备。
- `stream`：采集麦克风并推流。
- `stream-wav`：读取 WAV 文件并推流。

`stream` 与 `stream-wav` 默认使用：

```text
audio.format = opus
sample_rate = 16000
channels = 1
frame_duration_ms = 20
asr.provider = dashscope
asr.hotword_id = None
intent.enabled = True
intent.user_semantics.client_id = 工匠汇
```

### 2.2 配置模型

位置：

```text
src/cloud_stt_client/config.py
```

核心配置：

- `AudioConfig`：传输格式、采样率、声道、帧长、设备 ID。
- `VadConfig`：提交给服务端的 VAD 参数。
- `AsrConfig`：ASR provider 标识。
- `AsrConfig.hotword_id`：可选热词表 ID。
- `UserSemanticsConfig`：意图识别所需的客户、企业和机器人设备标识。
- `IntentConfig`：意图识别开关、业务上下文、当前时间和地点。
- `ClientConfig`：REST 地址、WebSocket 地址、音频配置、队列容量和停止策略。

`AudioConfig.frame_samples` 和 `AudioConfig.frame_bytes` 用于统一 20ms 音频帧大小。默认 16kHz 单声道 20ms 对应 320 samples 和 640 bytes PCM。

### 2.3 设备选择与长期偏好

位置：

```text
src/cloud_stt_client/audio/devices.py
src/cloud_stt_client/preferences.py
```

选择顺序：

1. 显式传入的 `device_id`。
2. 本地偏好文件中的历史输入设备。
3. 系统 default 输入设备。
4. Host API 优先级匹配。
5. 第一个可用输入设备。

当用户显式传入 `--device-id` 时，`AudioCapture` 会通过 `remember_explicit=True` 保存设备信息。偏好文件记录设备 index、name 和 hostapi。后续设备 index 变化时，代码会继续尝试通过 name 和 hostapi 匹配。

### 2.4 音频采集

位置：

```text
src/cloud_stt_client/audio/capture.py
```

实现要点：

- 使用 `sounddevice.InputStream` 打开输入设备。
- 按设备原生采样率和声道采集。
- 采集回调中执行轻量音频转换。
- 使用 `asyncio.Queue` 将音频线程和网络发送解耦。
- 队列满时丢弃旧帧，保留最新实时音频。

### 2.5 音频处理

位置：

```text
src/cloud_stt_client/audio/processing.py
```

处理流程：

```text
float32 输入
-> 下混为 mono
-> 线性重采样到 16kHz
-> 裁剪到 [-1.0, 1.0]
-> 转为 little-endian int16 PCM
-> 固定 20ms 分帧
```

`AudioFrameConverter` 内部维护 pending buffer，保证网络层收到固定协议帧。停止采集时通过 `flush()` 对尾帧补零。

### 2.6 WAV 输入

位置：

```text
src/cloud_stt_client/audio/wav_source.py
```

`stream-wav` 只接受：

```text
16kHz / mono / 16-bit PCM / uncompressed
```

读取后按 `AudioConfig.frame_bytes` 切分固定帧。不足一帧时补零。

### 2.7 传输编码

位置：

```text
src/cloud_stt_client/encoding.py
```

编码器：

- `PcmPassthroughEncoder`：直接发送 PCM16。
- `OpusEncoder`：将 PCM16 编码为 Opus。

`create_encoder()` 根据 `AudioConfig.format` 创建编码器。Opus 动态库查找顺序：

1. `CLOUD_STT_OPUS_LIB`
2. `libs/libopus/...`
3. 系统库路径

### 2.8 协议客户端

位置：

```text
src/cloud_stt_client/protocol.py
```

组件：

- `RestSessionClient`：创建 STT 会话。
- `SttWebSocketClient`：建立 WebSocket、发送音频帧、发送 commit、接收事件。
- `websocket_url_with_session()`：为手工 WebSocket 地址附加 session 参数。

### 2.9 客户端管线

位置：

```text
src/cloud_stt_client/pipeline.py
```

麦克风模式：

```text
REST 创建会话
-> 创建编码器
-> 建立 WebSocket
-> 启动事件接收任务
-> 打开 AudioCapture
-> 读取 PCM frame
-> 编码
-> 发送二进制帧
-> 收到 stt.final 或 error 后结束
```

WAV 模式使用同一套协议和编码逻辑，只把音频来源替换为 `iter_wav_frames()`。

## 3. 服务端实现

### 3.1 FastAPI 应用

位置：

```text
src/cloud_stt_server/app.py
```

HTTP 路由：

- `GET /health`
- `POST /stt/v1/sessions`
- `GET /stt/v1/sessions/{session_id}`
- `DELETE /stt/v1/sessions/{session_id}`

WebSocket 路由：

- `/stt/v1/stream?session_id=...`

WebSocket 处理过程：

```text
读取 session
-> 初始化 AudioDecoder
-> 初始化 RollingAudioBuffer
-> 初始化 AsyncAudioChunkQueue
-> 初始化 FsmnVadTracker
-> 根据 asr.provider 创建 RealtimeAsr
-> 并发接收客户端音频和 ASR 事件
-> 解码音频
-> VAD 判断语音状态
-> 语音开始后将音频写入 ASR 待发送队列
-> 后台发送任务按顺序调用 ASR provider
-> 语音结束或 commit 后停止 ASR
-> 返回 final 文本和意图适配结果
```

### 3.2 协议模型

位置：

```text
src/cloud_stt_server/protocol.py
```

核心模型：

- `AudioParams`
- `VadParams`
- `AsrParams`
- `IntentParams`
- `UserSemantics`
- `CreateSessionRequest`
- `CreateSessionResponse`
- `SessionStatusResponse`
- `SttPartialMessage`
- `SttFinalMessage`
- `ErrorMessage`

默认协议参数：

```text
audio.format = opus
audio.sample_rate = 16000
audio.channels = 1
audio.frame_duration_ms = 20
vad.engine = fsmn
asr.provider = dashscope
asr.hotword_id = None
intent.enabled = True
intent.user_semantics.client_id = 工匠汇
```

### 3.3 会话管理

位置：

```text
src/cloud_stt_server/sessions.py
```

`SessionStore` 使用内存字典保存会话，默认 TTL 为 300 秒。每个会话包含音频参数、VAD 参数、ASR 参数、意图上下文参数、创建时间、过期时间、WebSocket 绑定状态和识别文本缓存。

### 3.4 音频解码

位置：

```text
src/cloud_stt_server/audio/decoder.py
src/cloud_stt_server/audio/pcm.py
```

服务端输入支持：

| 输入格式 | 处理方式 |
| --- | --- |
| `opus` | 使用 opuslib 解码为 PCM16 |
| `pcm_s16le` | 校验后直接进入后续链路 |

所有后续模块统一处理 16kHz mono PCM16。

### 3.5 音频缓冲与队列

位置：

```text
src/cloud_stt_server/audio/rolling_buffer.py
src/cloud_stt_server/audio/queue.py
```

`RollingAudioBuffer` 保存语音起点前的回溯音频，默认由 `vad.pre_roll_ms` 控制。

`AudioChunkQueue` 是同步音频块容量保护工具，按累计音频时长限制缓存大小。

`AsyncAudioChunkQueue` 负责 ASR 待发送音频排队。WebSocket 接收循环只负责解码、VAD 和入队，后台发送任务按顺序调用 `asr.send_audio()`。如果某次 ASR 发送阻塞，接收循环仍可继续接收后续音频并写入等待队列；等待队列按累计音频时长限制容量，默认由 `AudioConfig.max_queue_seconds = 30` 控制。超过上限时返回 `audio chunk queue is full` 错误并结束当前会话。

### 3.6 FSMN-VAD

位置：

```text
src/cloud_stt_server/vad/fsmn_vad.py
```

`FsmnVadTracker` 使用 FunASR `AutoModel` 加载 FSMN-VAD 模型。输入 PCM16 后转换为 float32 ndarray，调用模型得到流式语音片段。

状态输出：

- `speech_start`
- `speech_end`
- `start_time_ms`
- `end_time_ms`

服务端根据 VAD 状态控制 ASR 音频发送：

- 未检测到语音：音频进入 rolling buffer。
- 检测到语音开始：pre-roll 和当前帧进入 ASR 待发送队列。
- 检测到语音结束：等待 ASR 待发送队列清空，停止 ASR 并返回最终文本。

### 3.7 ASR 抽象层

位置：

```text
src/cloud_stt_server/asr/base.py
src/cloud_stt_server/asr/factory.py
src/cloud_stt_server/asr/dashscope_realtime.py
```

抽象接口：

```python
class RealtimeAsr:
    async def start(self) -> None: ...
    async def send_audio(self, data: bytes) -> None: ...
    async def stop(self) -> str: ...
```

工厂函数：

```python
create_realtime_asr(provider, config, on_event, hotword_id=None)
```

当前 provider：

| provider | 实现 |
| --- | --- |
| `dashscope` | `DashScopeRealtimeAsr` |

新增 ASR provider 时，实现 `RealtimeAsr` 子类并在 `factory.py` 中注册。

### 3.8 DashScope 实时 ASR

位置：

```text
src/cloud_stt_server/asr/dashscope_realtime.py
```

实现要点：

- 使用 `dashscope.audio.asr.Recognition`。
- 通过线程封装同步 SDK 调用。
- 将会话中的 `hotword_id` 映射为 DashScope `phrase_id`。
- 将 SDK 回调转换为统一事件。
- 输出 `asr.start`、`stt.partial`、`stt.final` 和 `error`。
- 停止时返回最近一次 final 文本。

### 3.9 文本适配

位置：

```text
src/cloud_stt_server/adapter/text_adapter.py
```

`normalize_asr_text()` 负责清理模型标签和多余空白，为后续指令解析提供稳定文本。

`build_intent_request()` 将最终 ASR 文本和会话上下文转换为意图识别输入：

```json
{
  "sn": "stt_xxx",
  "query": "请向前走",
  "user_semantics": {
    "client_id": "工匠汇",
    "enterprise_id": "ent_1",
    "device_id": "robot_1",
    "deviceid": null
  },
  "current_time": "星期二 2026-05-26 10:00:00",
  "location": "苏州"
}
```

`command_to_partner_response()` 将 `RobotCommand` 转换为统一意图结果：

```json
{
  "status": 1,
  "error": "",
  "nlp": [
    {
      "english_domain": "robot_control",
      "slots": {
        "matched_text": "向前"
      },
      "source": "xiaozhi_cloud_stt",
      "intent": "move_forward",
      "feed": {
        "image": [],
        "video": [],
        "audio": []
      },
      "answer": "请向前走"
    }
  ],
  "msg": "返回成功"
}
```

### 3.10 文本转指令

位置：

```text
src/cloud_stt_server/command/
```

模块：

- `base.py`：`TextCommandParser` 抽象接口。
- `models.py`：`RobotCommand`、意图请求模型和意图响应模型。
- `rule_parser.py`：关键词规则解析器。

`RobotCommand` 字段：

```text
intent
raw_text
params
confidence
parser
recognized
```

`TextCommandParser` 提供两个入口：

```python
def parse(text: str) -> RobotCommand: ...
def parse_request(request: IntentRecognitionRequest) -> RobotCommand: ...
```

服务端在 `stt.final` 事件生成时调用文本适配层和解析器，并将意图结果挂载到 final 事件的 `intent` 字段。

## 4. 扩展规范

### 4.1 新增 ASR Provider

1. 在 `src/cloud_stt_server/asr/` 下新增实现类。
2. 继承 `RealtimeAsr`。
3. 实现 `start()`、`send_audio()`、`stop()`。
4. 将 provider 名称加入 `SUPPORTED_ASR_PROVIDERS`。
5. 在 `create_realtime_asr()` 中增加路由分支。
6. 为 provider 校验、工厂路由和事件输出补充测试。

### 4.2 新增音频格式

1. 在客户端 `encoding.py` 中增加编码器。
2. 在服务端 `audio/decoder.py` 中增加解码器。
3. 更新 `AudioParams.format` 类型。
4. 更新 `ServerConfig.audio.supported_formats`。
5. 补充协议、编码和解码测试。

### 4.3 新增指令解析器

1. 实现 `TextCommandParser`。
2. 返回统一 `RobotCommand`。
3. 保持 `unknown` 作为兜底 intent。
4. 对命中、未命中、空文本和边界词补充测试。

### 4.4 接入机器人执行器

推荐新增模块：

```text
src/cloud_stt_server/robot/
  base.py
  mock_executor.py
  http_executor.py
```

建议接口：

```python
async def execute(command: RobotCommand) -> RobotCommandResult:
    ...
```

机器人执行应与 ASR 解耦。服务端可在收到 `stt.final` 后调用文本解析器，再将 `RobotCommand` 交给执行器。

## 5. 测试

测试目录：

```text
tests/
```

覆盖范围：

- 客户端音频转换。
- 输入设备选择与长期偏好。
- WAV 读取与分帧。
- WebSocket URL 处理。
- Opus 动态库查找。
- PCM 回退编码器。
- Opus 编解码往返集成测试。
- 服务端 PCM 解码。
- RollingBuffer。
- AudioChunkQueue。
- AsyncAudioChunkQueue 阻塞排队和满队列保护。
- FSMN-VAD 状态解析。
- REST 健康检查。
- REST 会话创建和查询。
- ASR provider 校验。
- ASR 热词参数透传。
- WebSocket 初始化异常返回。
- 文本清洗。
- 文本转机器人指令规则解析。
- 意图识别输入参数格式适配。
- 意图识别输出格式适配。
- final 事件意图结果挂载。

运行命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests -q -p no:cacheprovider
```

当前结果：

```text
36 passed, 1 skipped
```

## 6. 编码约定

- 客户端和服务端协议参数通过 dataclass 或 Pydantic model 表达。
- 服务端外部 ASR 只通过 `RealtimeAsr` 抽象接入。
- WebSocket 返回事件使用 JSON object。
- 音频进入 VAD 和 ASR 前统一为 16kHz mono PCM16。
- Opus 仅作为传输编码，服务端解码后再进入后续处理。
- 密钥只通过环境变量注入。
- 测试中避免依赖真实麦克风、真实云端 ASR 和真实 FSMN 模型下载。
