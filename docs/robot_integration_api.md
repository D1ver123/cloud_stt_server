# 机器人端 STT 接入接口文档

本文档面向不使用 Python 客户端的机器人端。机器人端只需要实现 HTTP 创建会话、WebSocket 推送音频和接收 JSON 事件。

## 接入流程

```text
HTTP POST /stt/v1/sessions 创建会话
-> 使用返回的 websocket_url 建立 WebSocket
-> WebSocket binary 发送音频帧
-> WebSocket text 接收识别事件
-> 发送 {"type":"commit"} 或关闭连接结束会话
```

推荐第一版使用 PCM 直传：

```text
format = pcm_s16le
sample_rate = 16000
channels = 1
frame_duration_ms = 20
frame_bytes = 640
```

如果使用 Opus，机器人端负责编码，服务端只负责解码。

## 服务地址

示例：

```text
http://服务器IP:8000
ws://服务器IP:8000
```

必须包含实际端口。服务端如果只监听 `127.0.0.1`，外部机器人无法直接访问，需要改为监听 `0.0.0.0` 或通过反向代理暴露。

## 创建会话

```http
POST /stt/v1/sessions
Content-Type: application/json
```

请求体：

```json
{
  "audio": {
    "format": "pcm_s16le",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration_ms": 20
  },
  "vad": {
    "engine": "fsmn",
    "pre_roll_ms": 200
  },
  "asr": {
    "provider": "doubao"
  },
  "intent": {
    "enabled": true,
    "user_semantics": {
      "client_id": "robot_client",
      "enterprise_id": "ent_1",
      "device_id": "robot_1"
    },
    "current_time": "",
    "location": ""
  }
}
```

响应：

```json
{
  "session_id": "stt_xxx",
  "websocket_url": "ws://服务器IP:8000/stt/v1/stream?session_id=stt_xxx",
  "expires_in_seconds": 300
}
```

## 发送音频

连接 `websocket_url` 后，通过 WebSocket binary 发送音频。

PCM 直传时每帧：

```text
16kHz
mono
signed 16-bit little-endian
20ms
640 bytes
```

不要把音频包装成 JSON，也不要 base64。

结束当前说话时发送 WebSocket text：

```json
{"type":"commit"}
```

如果需要一条连接内连续识别多句话，可以不立即发送 `commit`，由服务端 VAD 自动判断语音结束并返回多次 `stt.final`。

## 接收事件

ASR 启动：

```json
{"type":"asr.start","provider":"doubao"}
```

中间结果：

```json
{"type":"stt.partial","text":"向前"}
```

最终结果：

```json
{
  "type": "stt.final",
  "text": "向前走",
  "intent": {
    "status": 1,
    "error": "",
    "nlp": [
      {
        "english_domain": "robot_control",
        "slots": {
          "matched_text": "向前"
        },
        "source": "cloud_stt",
        "intent": "move_forward",
        "feed": {
          "image": [],
          "video": [],
          "audio": []
        },
        "answer": "向前走"
      }
    ],
    "msg": "返回成功"
  }
}
```

错误：

```json
{"type":"error","message":"error detail"}
```

## 常见错误

| message | 含义 | 处理 |
| --- | --- | --- |
| `missing session_id` | WebSocket URL 缺少 session_id | 使用创建会话返回的 `websocket_url` |
| `invalid or expired session_id` | 会话不存在或过期 | 重新创建 session |
| `unsupported audio format` | 音频格式不支持 | 使用 `pcm_s16le` 或 `opus` |
| `only 16000 Hz audio is supported` | 采样率错误 | 重采样到 16kHz |
| `only mono audio is supported` | 声道数错误 | 转单声道 |
| `audio chunk queue is full` | 服务端 ASR 发送阻塞 | 结束当前会话，稍后重试 |
| `Missing Doubao ASR credentials` | 服务端未配置豆包 ASR Key | 联系服务端运维 |

## 最小伪代码

```python
session = http_post(
    "http://服务器IP:8000/stt/v1/sessions",
    json={
        "audio": {
            "format": "pcm_s16le",
            "sample_rate": 16000,
            "channels": 1,
            "frame_duration_ms": 20,
        },
        "vad": {"engine": "fsmn", "pre_roll_ms": 200},
        "asr": {"provider": "doubao"},
        "intent": {"enabled": True},
    },
)

ws = websocket_connect(session["websocket_url"])

while robot_is_recording:
    pcm_frame = robot_audio.read_20ms_pcm16_16k_mono()
    ws.send_binary(pcm_frame)

ws.send_text('{"type":"commit"}')

while True:
    event = ws.recv_json()
    if event["type"] == "stt.final":
        robot.handle_text(event["text"])
        robot.handle_intent(event.get("intent"))
        break
    if event["type"] == "error":
        robot.handle_error(event["message"])
        break

ws.close()
```
