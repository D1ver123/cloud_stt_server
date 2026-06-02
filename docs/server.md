# 服务端说明

服务端包名为 `cloud_stt_server`，基于 FastAPI 提供 REST 和 WebSocket 接口。

## 能力

- `GET /health` 健康检查。
- `POST /stt/v1/sessions` 创建 STT 会话。
- `GET /stt/v1/sessions/{session_id}` 查询会话状态。
- `DELETE /stt/v1/sessions/{session_id}` 删除会话。
- `WS /stt/v1/stream?session_id=...` 接收音频流并返回识别事件。
- 支持 `pcm_s16le` 和 `opus` 输入。
- 服务端统一处理 `16kHz mono PCM16`。
- 使用 FunASR FSMN-VAD 判断语音开始和结束。
- 默认使用豆包流式语音识别模型 2.0 做实时 ASR，默认不传 `language`，走中文默认模型能力以覆盖普通话和主流中文方言。
- 对最终文本进行规则意图解析。

## 运行

```bash
export DOUBAO_ASR_API_KEY="your_key"
export CLOUD_STT_HOST="0.0.0.0"
export CLOUD_STT_PORT="8000"
python -m cloud_stt_server.app
```

或：

```bash
python -m uvicorn cloud_stt_server.app:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## WebSocket 处理流程

```text
校验 session_id
-> 初始化音频解码器
-> 初始化 pre-roll 音频缓冲
-> 初始化 ASR 待发送队列
-> 初始化 FSMN-VAD
-> 初始化豆包 ASR provider
-> 接收客户端 binary 音频
-> 解码为 PCM16
-> VAD 判断语音起止
-> 语音段进入 ASR 队列
-> 后台任务发送音频给豆包 ASR
-> 返回 asr.start / stt.partial / stt.final / error
```

一次 WebSocket 连接内可以处理多段语音。服务端在返回 `stt.final` 后不会主动关闭连接，会继续等待后续音频。客户端主动发送 `commit` 或关闭连接时，本轮会话结束。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CLOUD_STT_HOST` | `0.0.0.0` | 监听地址 |
| `CLOUD_STT_PORT` | `8000` | 监听端口 |
| `DOUBAO_ASR_API_KEY` | 无 | 火山引擎新版控制台 API Key；旧版控制台可用 `DOUBAO_ASR_APP_KEY` + `DOUBAO_ASR_ACCESS_KEY` |
| `DOUBAO_ASR_RESOURCE_ID` | `volc.seedasr.sauc.duration` | 豆包流式语音识别模型 2.0 小时版；并发版用 `volc.seedasr.sauc.concurrent` |
| `DOUBAO_ASR_ENDPOINT` | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async` | 豆包流式 ASR WebSocket 地址 |
| `DOUBAO_ASR_LANGUAGE` | 未设置 | 默认不传，使用中文默认模型能力，覆盖普通话和主流中文方言 |
| `DOUBAO_ASR_ENABLE_NONSTREAM` | `true` | 开启二遍识别，提高最终分句准确率 |
| `DASHSCOPE_API_KEY` | 无 | 可选：仅当 `asr.provider=dashscope` 时使用 |
| `FSMN_VAD_MODEL` | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` | VAD 模型名或本地路径 |
| `FSMN_VAD_DEVICE` | `cpu` | VAD 推理设备 |
| `FSMN_VAD_CHUNK_SIZE_MS` | `200` | VAD 流式块大小 |
| `FSMN_VAD_MAX_END_SILENCE_TIME_MS` | `800` | 语音结束静音阈值 |

## 反向代理

如果使用 Nginx，必须保留 WebSocket Upgrade：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}
```

如果客户端空闲超时时间大于 60 秒，反向代理超时也要相应调大。

## 常见错误

| 错误 | 含义 |
| --- | --- |
| `unsupported audio format` | 只支持 `pcm_s16le` 和 `opus` |
| `only 16000 Hz audio is supported` | 当前服务端只接收 16kHz |
| `only mono audio is supported` | 当前服务端只接收单声道 |
| `Missing Doubao ASR credentials` | 服务端未配置豆包 ASR Key |
| `audio chunk queue is full` | ASR 发送阻塞，服务端等待队列已满 |
