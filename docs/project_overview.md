# xiaozhi-cloud-stt 项目说明文档

## 1. 项目定位

`xiaozhi-cloud-stt` 是一套实时语音转文字服务，用于将用户端麦克风或 WAV 音频转换为可被机器人业务层消费的文本结果，并预留文本转机器人动作指令的解析接口。

系统由客户端和服务端组成：

- 客户端负责音频设备选择、音频采集、音频格式转换、Opus 编码、会话创建和音频流推送。
- 服务端负责会话管理、音频解码、FSMN-VAD 语音活动检测、ASR 待发送队列、实时 ASR 路由、DashScope 实时语音识别和识别结果返回。
- 指令层负责将最终识别文本转换为结构化机器人指令，当前已提供接口与规则解析器。

流程图文件位于：

```text
docs/img.png
```

## 2. 系统链路

```text
麦克风 / WAV
-> 音频转换为 16kHz mono PCM16
-> Opus 编码
-> REST 创建 STT 会话
-> WebSocket 推送音频帧
-> 服务端 Opus 解码为 PCM16
-> FSMN-VAD 判断语音起止
-> ASR Provider 路由
-> ASR 待发送队列按累计音频时长限流
-> DashScope fun-asr-realtime 实时识别
-> 返回 stt.partial / stt.final / error
-> 文本转机器人指令接口
```

## 3. 当前功能

### 3.1 客户端能力

- 枚举本机输入设备。
- 优先使用长期记忆的麦克风。
- 未配置记忆设备时使用系统 default 输入设备。
- 显式选择 `--device-id` 后自动保存为长期偏好。
- 支持麦克风实时采集。
- 支持 16kHz mono 16-bit PCM WAV 文件推流。
- 支持设备原生采样率到 16kHz 的转换。
- 支持多声道输入下混为单声道。
- 默认使用 Opus 作为传输编码。
- 支持显式回退到 `pcm_s16le`。
- 支持 REST 会话创建与 WebSocket 音频推流。

客户端偏好文件默认路径：

```text
%APPDATA%\xiaozhi-cloud-stt\client_preferences.json
```

可通过环境变量覆盖：

```text
CLOUD_STT_CLIENT_PREFS
```

### 3.2 服务端能力

- FastAPI REST 服务。
- WebSocket 音频流处理。
- 会话创建、查询和删除。
- 会话 TTL 管理。
- 支持 `opus` 与 `pcm_s16le` 输入。
- 服务端统一转换为 16kHz mono PCM16。
- FunASR FSMN-VAD 流式语音活动检测。
- 语音起点前音频回溯缓存。
- ASR 待发送音频队列容量保护，避免云端 SDK 发送阻塞时无限积压。
- ASR 抽象接口与 provider 工厂。
- DashScope `fun-asr-realtime` 实时 ASR 实现。
- 支持会话级热词表 ID。
- ASR 事件标准化输出。
- 最终识别文本会进入文本适配层和意图解析器，输出兼容合作方调用风格的结构化结果。
- WebSocket 初始化和处理异常以 JSON error 事件返回。

### 3.3 指令解析能力

服务端已预留文本转机器人指令接口，当前规则解析器支持：

| intent | 示例 |
| --- | --- |
| `move_forward` | 前进、向前、向前走 |
| `move_backward` | 后退、向后、倒退 |
| `turn_left` | 左转、向左、左拐 |
| `turn_right` | 右转、向右、右拐 |
| `stop` | 停止、停下、暂停 |
| `unknown` | 未匹配文本 |

内部指令结构：

```json
{
  "intent": "move_forward",
  "raw_text": "请向前走",
  "params": {
    "matched_text": "向前"
  },
  "confidence": 1.0,
  "parser": "rule"
}
```

对外意图结果使用统一 `status/error/nlp/msg` 结构：

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

## 4. 协议说明

### 4.1 创建会话

```http
POST /stt/v1/sessions
Content-Type: application/json
```

请求示例：

```json
{
  "audio": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration_ms": 20
  },
  "vad": {
    "engine": "fsmn",
    "pre_roll_ms": 200
  },
  "asr": {
    "provider": "dashscope",
    "hotword_id": "phrase_xxx"
  },
  "intent": {
    "enabled": true,
    "user_semantics": {
      "client_id": "工匠汇",
      "enterprise_id": "ent_1",
      "device_id": "robot_1"
    },
    "current_time": "星期二 2026-05-26 10:00:00",
    "location": "苏州"
  }
}
```

`hotword_id` 为可选字段。使用 DashScope ASR provider 时，该字段会作为实时识别的 `phrase_id` 参数传入。

`intent` 为可选字段，用于传递后续意图识别所需的业务上下文。服务端会把最终 ASR 文本适配为：

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

响应示例：

```json
{
  "session_id": "stt_xxx",
  "websocket_url": "ws://127.0.0.1:8000/stt/v1/stream?session_id=stt_xxx",
  "expires_in_seconds": 300
}
```

### 4.2 查询会话

```http
GET /stt/v1/sessions/{session_id}
```

响应包含音频参数、VAD 参数、ASR provider、热词表 ID、意图上下文参数、创建时间、过期时间和 WebSocket 绑定状态。

### 4.3 删除会话

```http
DELETE /stt/v1/sessions/{session_id}
```

### 4.4 WebSocket 推流

连接地址由创建会话接口返回。客户端发送二进制音频帧，服务端返回 JSON 事件：

```json
{"type": "asr.start", "provider": "dashscope"}
```

```json
{"type": "stt.partial", "text": "打开"}
```

```json
{
  "type": "stt.final",
  "text": "请向前走",
  "intent": {
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
}
```

```json
{"type": "error", "message": "错误信息"}
```

如果 ASR provider 的单次发送调用阻塞，服务端会继续接收已进入语音段的后续音频并写入 ASR 待发送队列；当等待队列累计音频时长超过上限时，返回：

```json
{"type": "error", "message": "audio chunk queue is full"}
```

客户端也可以发送结束消息：

```json
{"type": "commit"}
```

## 5. 环境变量

### 5.1 服务端

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CLOUD_STT_HOST` | `0.0.0.0` | 服务监听地址 |
| `CLOUD_STT_PORT` | `8000` | 服务监听端口 |
| `DASHSCOPE_API_KEY` | 无 | DashScope API Key |
| `DASHSCOPE_ASR_MODEL` | `fun-asr-realtime` | DashScope 实时 ASR 模型 |
| `DASHSCOPE_ASR_FORMAT` | `pcm` | 发送给 ASR 的音频格式 |
| `DASHSCOPE_ASR_SAMPLE_RATE` | `16000` | ASR 采样率 |
| `DASHSCOPE_ASR_DISFLUENCY_REMOVAL` | `false` | 是否启用顺滑处理 |
| `FSMN_VAD_MODEL` | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` | FSMN-VAD 模型名或本地目录 |
| `FSMN_VAD_DEVICE` | `cpu` | VAD 推理设备 |
| `FSMN_VAD_SAMPLE_RATE` | `16000` | VAD 采样率 |
| `FSMN_VAD_CHUNK_SIZE_MS` | `200` | VAD 流式块大小 |
| `FSMN_VAD_MAX_END_SILENCE_TIME_MS` | `800` | 语音结束静音阈值 |
| `FSMN_VAD_NCPU` | `4` | FunASR CPU 线程数 |

### 5.2 客户端

| 变量 | 说明 |
| --- | --- |
| `CLOUD_STT_OPUS_LIB` | 指定原生 libopus / opus.dll 路径 |
| `CLOUD_STT_CLIENT_PREFS` | 指定客户端偏好文件路径 |

## 6. 运行方式

### 6.1 安装依赖

```powershell
conda activate myenv
cd "D:\myproject\pythonProject\xiaozhi-cloud-stt"
pip install -r requirements-dev.txt
```

Opus 需要 Python 包和原生动态库。conda 环境可使用：

```powershell
conda install -c conda-forge libopus opuslib
```

### 6.2 启动服务端

```powershell
conda activate myenv
cd "D:\myproject\pythonProject\xiaozhi-cloud-stt"
$env:PYTHONPATH = (Resolve-Path .\src).Path
$env:DASHSCOPE_API_KEY = "你的 DashScope API Key"
python -m cloud_stt_server.app
```

或：

```powershell
python -m uvicorn cloud_stt_server.app:app --host 0.0.0.0 --port 8000
```

### 6.3 枚举麦克风

```powershell
python -m cloud_stt_client.cli list-devices
```

### 6.4 麦克风推流

使用自动设备选择：

```powershell
python -m cloud_stt_client.cli stream --server http://127.0.0.1:8000 --duration 30
```

显式选择并记忆麦克风：

```powershell
python -m cloud_stt_client.cli stream --server http://127.0.0.1:8000 --device-id 设备ID --duration 30
```

携带热词表 ID：

```powershell
python -m cloud_stt_client.cli stream --server http://127.0.0.1:8000 --hotword-id phrase_xxx --duration 30
```

携带意图识别上下文：

```powershell
python -m cloud_stt_client.cli stream --server http://127.0.0.1:8000 --intent-client-id 工匠汇 --intent-enterprise-id ent_1 --intent-device-id robot_1 --location 苏州 --duration 30
```

### 6.5 WAV 推流

WAV 文件要求：

```text
16kHz / mono / 16-bit PCM / uncompressed
```

命令：

```powershell
python -m cloud_stt_client.cli stream-wav .\test.wav --server http://127.0.0.1:8000 --realtime
```

### 6.6 PCM 回退

```powershell
python -m cloud_stt_client.cli stream --server http://127.0.0.1:8000 --audio-format pcm_s16le --duration 30
```

## 7. 部署说明

云服务器推荐环境：

```text
Linux x86_64
Python 3.10 或 3.11
2C4G 以上
公网可访问 DashScope
开放服务端口 8000 或通过反向代理转发
```

部署时配置：

```bash
export PYTHONPATH=/opt/xiaozhi-cloud-stt/src
export DASHSCOPE_API_KEY=your_dashscope_key
export DASHSCOPE_ASR_MODEL=fun-asr-realtime
export FSMN_VAD_MODEL=/opt/xiaozhi-cloud-stt/models/speech_fsmn_vad_zh-cn-16k-common-pytorch
export FSMN_VAD_DEVICE=cpu
```

启动：

```bash
python -m uvicorn cloud_stt_server.app:app --host 0.0.0.0 --port 8000
```

生产环境可使用 systemd、Supervisor、Docker 或云厂商进程托管能力管理进程。对公网提供服务时应使用 HTTPS/WSS、访问鉴权、日志轮转和密钥托管。

## 8. 测试状态

测试命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests -q -p no:cacheprovider
```

当前验证结果：

```text
36 passed, 1 skipped
```
