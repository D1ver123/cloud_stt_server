# 外部机器人 Opus 音频流接入交付文档

本文档面向机器人端开发与联调人员，说明机器人如何把本地 PCM 音频编码为 Opus，并通过 WebSocket 推送到 STT 服务端，随后接收服务端返回的识别结果。

## 1. 交付目标

本次交付验证以下链路：

```text
机器人端 PCM 音频
-> 机器人端 Opus 编码
-> HTTP 创建 STT 会话
-> WebSocket 连接会话
-> WebSocket binary 发送 Opus 音频包
-> WebSocket text 发送 commit
-> 服务端返回 stt.partial / stt.final / error
-> 机器人端接收最终识别结果
```

配套联调工具：

```text
external_robot_opus_sim.py
```

该脚本用于机器人端协议联调，覆盖会话创建、Opus 编码、WebSocket 推流、结果接收与首字输出计时。

## 2. 交付物

| 文件 | 说明 |
| --- | --- |
| `external_robot_opus_sim.py` | 外部机器人联调工具。输入裸 PCM，编码 Opus，通过 WebSocket 推流。 |
| `docs/external_robot_opus_delivery.md` | 本交付文档。 |
| `docs/robot_integration_api.md` | 通用机器人接入接口文档。 |

## 3. 机器人端接入能力要求

机器人端接入需覆盖以下能力：

```text
1. HTTP POST 创建 session
2. 解析返回的 websocket_url
3. 连接 WebSocket
4. 将 PCM 按 20ms 分帧
5. 对每帧 PCM 做 Opus 编码
6. 使用 WebSocket binary 发送 Opus packet
7. 说完后使用 WebSocket text 发送 {"type":"commit"}
8. 持续接收服务端 text JSON
9. 以 stt.final 作为最终识别结果
```

WebSocket URL 用于建立双向通信连接。连接建立后，机器人端按协议执行音频分帧、Opus 编码、binary 发送、commit 发送、服务端事件接收和会话关闭。

## 4. 音频输入要求

机器人端原始输入为裸 PCM：

```text
sample_rate = 16000
channels = 1
sample_format = signed 16-bit little-endian PCM
frame_duration_ms = 20
frame_samples = 320
frame_bytes = 640
```

计算方式：

```text
16000 samples/s * 0.02 s * 1 channel * 2 bytes = 640 bytes
```

机器人麦克风输出格式不满足上述要求时，机器人端需先完成：

```text
原始音频
-> 重采样到 16000 Hz
-> 转单声道
-> 转 signed int16 little-endian
-> 每 20ms 切一帧
-> Opus 编码
-> WebSocket binary 发送
```

Opus 编码参数：

```text
sample_rate = 16000
channels = 1
frame_duration_ms = 20
frame_size = 320 samples
application = VOIP
```

编码要求：

```text
1. 每 640 bytes PCM 编码为 1 个 Opus packet。
2. 每个 WebSocket binary message 只发送 1 个 Opus packet。
3. 不合并多个 Opus packet 到同一个 WebSocket message。
4. 不拆分单个 Opus packet 到多个 WebSocket message。
5. Opus bitrate 不由协议固定，需保证服务端可按 16kHz、mono、20ms 帧解码。
```

## 5. 服务端访问前置条件

服务端由服务端负责人部署、维护和保障可用性。机器人端联调前需获得服务端负责人提供的 HTTP 地址、WebSocket 地址、端口和网络访问策略。

机器人侧访问地址示例：

```text
http://36.140.148.12:8011
ws://36.140.148.12:8011
```

机器人端只需要访问 STT 服务地址，不配置、不保存、不传输服务端密钥。服务端密钥、运行环境变量、进程管理和日志排查均由服务端负责人处理。

## 6. 配套联调工具运行环境

`external_robot_opus_sim.py` 用于协议联调和链路验收。机器人端正式接入不依赖该工具运行环境。

联调工具依赖：

```text
Python 3.10+
websockets
opuslib
原生 libopus / opus.dll
```

安装 Python 依赖：

```powershell
python -m pip install websockets opuslib
```

原生 `opus.dll` 可通过环境变量指定：

```powershell
$env:CLOUD_STT_OPUS_LIB="D:\path\to\opus.dll"
```

脚本参数指定方式：

```powershell
python .\external_robot_opus_sim.py --opus-lib "D:\path\to\opus.dll"
```

## 7. 准备 PCM 测试音频

如果已有裸 PCM，可直接使用。

如果只有 WAV，可用 ffmpeg 转换：

```powershell
cd <联调工具目录>

ffmpeg -y -i .\zh_16k_mono.wav -ac 1 -ar 16000 -f s16le .\robot_audio.pcm
```

输出文件：

```text
robot_audio.pcm
```

WebSocket 中发送 Opus 编码后的 packet，不发送 WAV 文件或 base64 文本。

## 8. 运行外部机器人联调工具

```powershell
cd <联调工具目录>

python .\external_robot_opus_sim.py `
  --server http://36.140.148.12:8011 `
  --pcm .\robot_audio.pcm `
  --realtime `
  --client-id external_robot `
  --enterprise-id ent_1 `
  --device-id robot_1 `
  --location Suzhou
```

参数说明：

| 参数 | 示例值 | 说明 |
| --- | --- | --- |
| `--server` | `http://36.140.148.12:8011` | STT 服务端 HTTP 地址，以服务端负责人提供的实际地址为准。 |
| `--pcm` | `robot_audio.pcm` | 机器人端输入的裸 PCM 文件。 |
| `--sample-rate` | `16000` | PCM 采样率。服务端当前要求 16000。 |
| `--channels` | `1` | PCM 声道数。服务端当前要求单声道。 |
| `--frame-duration-ms` | `20` | 每帧时长。 |
| `--realtime` | 关闭 | 开启后按 20ms 节奏发送实时音频流。 |
| `--client-id` | `external_robot` | 业务侧机器人或客户标识。 |
| `--enterprise-id` | `ent_1` | 企业标识。 |
| `--device-id` | `robot_1` | 机器人设备标识。 |
| `--location` | 空 | 业务上下文位置。 |
| `--current-time` | 空 | 业务上下文时间。 |
| `--opus-lib` | 空 | 手动指定原生 libopus 路径。 |
| `--no-wait-asr-start` | 关闭 | 开启后 WebSocket 连接成功即发送音频；默认等待 `asr.start` 后再发送音频。 |

## 9. 脚本输出说明

创建会话成功后会输出：

```text
SESSION => {"session_id":"stt_xxx","websocket_url":"ws://...","expires_in_seconds":300}
```

发送结束后会输出：

```text
CLIENT => sent 123 opus frames and commit
```

服务端事件会输出：

```text
SERVER => {"type":"asr.start","provider":"dashscope"}
SERVER => {"type":"stt.partial","text":"打开"}
SERVER => {"type":"stt.final","text":"打开一号机器人","intent":{...}}
```

首字计时会输出：

```text
ROBOT_FIRST_CHAR => 打
TIMING => {"asr_start_ms":8.12,"first_audio_send_ms":12.34,"first_char":"打","first_char_recognized_ms":456.78,"first_audio_to_first_char_recognized_ms":444.44,"first_char_output_ms":456.91,"first_audio_to_first_char_output_ms":444.57,"recognize_to_output_delta_ms":0.13,"commit_sent_ms":1234.56}
```

计时字段含义：

| 字段 | 说明 |
| --- | --- |
| `asr_start_ms` | 脚本启动后收到服务端 `asr.start` 事件的时间。 |
| `first_audio_send_ms` | 脚本启动后，第一帧音频发送的时间。 |
| `first_char` | 首次收到的识别文本中的第一个字。 |
| `first_char_recognized_ms` | 脚本收到第一条带 `text` 的服务端事件并解析出首字的时间。 |
| `first_audio_to_first_char_recognized_ms` | 第一帧音频发送完成到脚本解析出首字的耗时，包含服务端 VAD、ASR 和网络返回时间。 |
| `first_char_output_ms` | 脚本把首字输出到控制台后的时间。 |
| `first_audio_to_first_char_output_ms` | 第一帧音频发送完成到脚本输出首字的端到端耗时，包含服务端 VAD、ASR、网络返回和机器人端输出时间。 |
| `recognize_to_output_delta_ms` | 脚本解析出首字到本地输出首字的耗时。 |
| `commit_sent_ms` | 发送 `{"type":"commit"}` 的时间。 |

首字端到端耗时以 `first_audio_to_first_char_output_ms` 为准。该指标包含 ASR 处理时间。

## 10. 协议细节

### 10.1 创建会话

请求：

```http
POST /stt/v1/sessions
Content-Type: application/json
```

请求体：

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
    "provider": "dashscope"
  },
  "intent": {
    "enabled": true,
    "user_semantics": {
      "client_id": "external_robot",
      "enterprise_id": "ent_1",
      "device_id": "robot_1"
    },
    "current_time": "",
    "location": "Suzhou"
  }
}
```

响应：

```json
{
  "session_id": "stt_xxx",
  "websocket_url": "ws://服务器IP:8011/stt/v1/stream?session_id=stt_xxx",
  "expires_in_seconds": 300
}
```

### 10.2 WebSocket 音频发送

机器人连接：

```text
ws://服务器IP:8011/stt/v1/stream?session_id=stt_xxx
```

音频包发送方式：

```text
WebSocket message type = binary
message payload = 单帧 Opus packet
```

每个 Opus packet 由一帧 20ms PCM 编码得到：

```text
640 bytes PCM -> Opus encode -> Opus packet -> WebSocket binary
```

推荐实时发送节奏：

```text
每 20ms 发送 1 个 Opus packet
```

### 10.3 结束本次语音

机器人端说完后发送 WebSocket text：

```json
{"type":"commit"}
```

该消息类型为 text，非 binary。

### 10.4 接收服务端结果

服务端通过 WebSocket text 返回 JSON。

ASR 启动事件：

```json
{
  "type": "asr.start",
  "provider": "dashscope"
}
```

中间识别结果：

```json
{
  "type": "stt.partial",
  "text": "打开"
}
```

最终识别结果：

```json
{
  "type": "stt.final",
  "text": "打开一号机器人",
  "intent": {}
}
```

错误事件：

```json
{
  "type": "error",
  "message": "错误原因"
}
```

机器人端以 `stt.final` 作为最终业务结果。`stt.partial` 仅作为中间识别结果。

## 11. 机器人端集成设计

机器人端推荐模块划分：

```text
AudioCapture
-> PcmNormalizer
-> OpusEncoder
-> SttSessionClient
-> SttWebSocketStreamer
-> SttEventHandler
```

状态机：

```text
idle
-> user_start_speaking
-> create_session
-> websocket_connect
-> start_receive_loop
-> stream_opus_audio
-> user_stop_speaking
-> send_commit
-> wait_final
-> handle_final
-> close_websocket
-> idle
```

核心伪代码：

```text
session = http_post("/stt/v1/sessions", audio_format="opus")

ws = websocket_connect(session.websocket_url)

start_receive_loop:
    event = ws.recv_json()
    if event.type == "stt.final":
        handle_final(event.text, event.intent)
    if event.type == "error":
        handle_error(event.message)

while user_is_speaking:
    pcm = mic.read_20ms_pcm16_16k_mono()
    opus_packet = opus.encode(pcm)
    ws.send_binary(opus_packet)
    sleep(20ms)

ws.send_text('{"type":"commit"}')
wait_until_final_or_timeout()
ws.close()
```

## 12. 验收标准

联调通过需要满足：

```text
1. 机器人端能成功 POST 创建 session。
2. 机器人端能连接 websocket_url。
3. 机器人端能持续发送 WebSocket binary Opus packet。
4. 服务端能返回 asr.start。
5. 服务端能返回 stt.partial 或 stt.final。
6. 机器人端能收到 stt.final。
7. stt.final.text 是有效识别文本。
8. 机器人端收到 error 时能停止当前会话并记录错误。
9. 首字计时字段能正常输出。
```

成功输出示例：

```text
SESSION => {"session_id":"stt_xxx","websocket_url":"ws://36.140.148.12:8011/stt/v1/stream?session_id=stt_xxx","expires_in_seconds":300}
SERVER => {"type":"asr.start","provider":"dashscope"}
SERVER => {"type":"stt.partial","text":"打开"}
ROBOT_FIRST_CHAR => 打
TIMING => {"asr_start_ms":7.34,"first_audio_send_ms":10.12,"first_char":"打","first_char_recognized_ms":520.33,"first_audio_to_first_char_recognized_ms":510.21,"first_char_output_ms":520.45,"first_audio_to_first_char_output_ms":510.33,"recognize_to_output_delta_ms":0.12}
CLIENT => sent 240 opus frames and commit
SERVER => {"type":"stt.final","text":"打开一号机器人","intent":{...}}
```

## 13. 异常与处理策略

### 13.1 WebSocket 连接建立后未收到结果

处理策略：

```text
1. 确认机器人端已发送 WebSocket binary Opus packet。
2. 确认机器人端已发送 text commit。
3. 确认发送的音频包含有效语音内容。
4. 确认服务端未返回 error。
5. 超时后关闭当前 WebSocket，并重新创建 session。
```

### 13.2 音频封装格式错误

处理策略：

```text
1. 实时推流协议发送 Opus packet，不发送 WAV 文件。
2. 每个 Opus packet 由 20ms PCM 帧编码得到。
3. WebSocket 音频消息类型为 binary。
4. 文本控制消息 {"type":"commit"} 的消息类型为 text。
```

### 13.3 收到 `Missing required environment variable: DASHSCOPE_API_KEY` 怎么办？

该错误表示服务端运行环境未读取到 DashScope Key。机器人端处理策略：

```text
1. 停止当前会话。
2. 记录错误信息和 session_id。
3. 将问题反馈给服务端负责人。
4. 服务端恢复后重新创建 session。
```

机器人端不配置、传输或保存 DashScope Key。

### 13.4 收到 `Opus support requires native libopus` 怎么办？

该错误可能发生在联调工具本地启动阶段，也可能由服务端通过 `error` 事件返回。

联调工具本地启动阶段报错时，设置本地 Opus 动态库路径：

```powershell
$env:CLOUD_STT_OPUS_LIB="D:\path\to\opus.dll"
```

或使用脚本参数：

```powershell
python .\external_robot_opus_sim.py --opus-lib "D:\path\to\opus.dll"
```

如果该错误由服务端 `error` 事件返回，机器人端记录错误并反馈给服务端负责人处理。

### 13.5 收到 `only 16000 Hz audio is supported` 怎么办？

机器人端创建 session 的 `sample_rate` 与服务端要求不一致，或音频实际采样率不匹配。需确保 PCM 为 16kHz。

### 13.6 收到 `only mono audio is supported` 怎么办？

机器人端创建 session 的 `channels` 与服务端要求不一致，或音频实际不是单声道。需在机器人端先混音为单声道。

### 13.7 收到 `invalid or expired session_id` 怎么办？

session 已过期或 WebSocket URL 使用错误。重新调用 `POST /stt/v1/sessions` 创建新会话，并使用新返回的 `websocket_url`。

## 14. 交付确认清单

机器人团队接入前确认：

- 服务端地址、端口、防火墙已确认。
- 服务端负责人已确认 STT 服务可用。
- 机器人端已具备 Opus 编码能力。
- 机器人端 PCM 输入为 16kHz、单声道、PCM16 little-endian。
- 机器人端每 20ms 编码并发送一个 Opus packet。
- WebSocket 音频消息使用 binary。
- `{"type":"commit"}` 使用 text。
- 机器人端以 `stt.final` 作为最终结果。
- 机器人端能记录和处理 `error`。
- 首字识别到首字输出的计时字段已接入或可通过参考脚本验证。
