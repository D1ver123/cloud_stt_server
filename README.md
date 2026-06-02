# cloud-stt

`cloud-stt` 是一套面向机器人语音交互的实时语音转文字服务。项目分为客户端和服务端：

- 客户端：本地麦克风采集、设备选择、音频格式转换、本地唤醒词检测、Opus/PCM 推流、WebSocket 事件接收。
- 服务端：STT 会话管理、WebSocket 音频接收、Opus/PCM 解码、FSMN-VAD、豆包流式语音识别模型 2.0、最终文本意图解析。

## 当前工作流程

```text
客户端本地监听麦克风
-> 本地 wake-word 小模型检测唤醒词
-> 唤醒后创建服务端 STT session
-> 建立 WebSocket
-> 进入空闲超时窗口，默认 60 秒
-> 音频同时上传服务端并继续喂给本地小模型
-> 服务端 VAD + 豆包流式 ASR 返回 stt.partial / stt.final
-> 每次 stt.partial / stt.final 都刷新空闲截止时间
-> 空闲窗口内允许多轮识别，不需要重复唤醒
-> 本地检测到 退出/停下/停止/结束，或连续 60 秒没有识别活动
-> 客户端写入本轮 stt.final 识别日志
-> 关闭本轮 WebSocket，回到本地唤醒监听
```

## 目录结构

```text
src/
  cloud_stt_client/     客户端：采集、唤醒、编码、推流、CLI
  cloud_stt_server/     服务端：FastAPI、VAD、ASR、意图解析
models/wake_word/       Sherpa-ONNX 唤醒词模型与 keywords.txt
scripts/run_server.py   本地服务端启动脚本
tests/                  单元测试
docs/client.md          客户端说明
docs/server.md          服务端说明
docs/robot_integration_api.md  机器人端协议说明
```

## 安装

建议 Python 3.10 或 3.11。

本地源码运行前必须先在当前 Python 环境中安装项目，否则执行 `python -m cloud_stt_client.cli ...` 会报 `ModuleNotFoundError: No module named 'cloud_stt_client'`。

```powershell
cd "D:\myproject\pythonProject\cloud-stt"
python -m pip install -e ".[audio,wake-word,opus,dev]"
```

如果只运行客户端，至少安装：

```powershell
python -m pip install -e ".[audio,wake-word,opus]"
```

如果只部署服务端：

```bash
python -m pip install -e .
```

临时调试时也可以不安装包，改用 `PYTHONPATH`：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

如果使用 Opus，需要系统存在原生 `libopus`。也可以通过环境变量指定：

```powershell
$env:CLOUD_STT_OPUS_LIB="D:\path\to\opus.dll"
```

## 服务端启动

服务端默认使用豆包流式语音识别模型 2.0，需要配置火山引擎豆包 ASR Key：

```bash
export DOUBAO_ASR_API_KEY="your_key"
export CLOUD_STT_HOST="0.0.0.0"
export CLOUD_STT_PORT="8000"
python -m cloud_stt_server.app
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

公网部署时确认云安全组、防火墙、反向代理均放通服务端端口。使用 Nginx 时必须支持 WebSocket Upgrade。

## 客户端运行

列出麦克风：

```powershell
python -m cloud_stt_client.cli list-devices
```

唤醒词模式，空闲 60 秒后退出：

```powershell
python -m cloud_stt_client.cli stream `
  --server http://服务器IP:8000 `
  --websocket-url ws://服务器IP:8000/stt/v1/stream `
  --wake-word `
  --wake-word-idle-timeout-seconds 60 `
  --audio-format pcm_s16le `
  --timing
```

不使用唤醒词，直接推流：

```powershell
python -m cloud_stt_client.cli stream `
  --server http://服务器IP:8000 `
  --audio-format pcm_s16le `
  --duration 20
```

WAV 文件推流要求 `16kHz / mono / 16-bit PCM / uncompressed`：

```powershell
python -m cloud_stt_client.cli stream-wav .\sample.wav `
  --server http://服务器IP:8000 `
  --audio-format pcm_s16le `
  --realtime
```

## WebSocket 事件

服务端会通过 WebSocket text JSON 返回事件：

```json
{"type":"asr.start","provider":"doubao"}
{"type":"stt.partial","text":"向前"}
{"type":"stt.final","text":"向前走","intent":{}}
{"type":"error","message":"error detail"}
```

客户端唤醒词相关事件：

```json
{"type":"wake_word.detected","text":"你好小旭"}
{"type":"wake_word.interrupted","text":"停下"}
{"type":"client.timing","stage":"wake_word_idle_timeout","elapsed_ms":60000.0}
{"type":"client.recognition_log","path":"logs/client_recognition/recognition_...json","result_count":1}
```

客户端默认在每轮 STT 会话结束后，把本轮所有 `stt.final` 最终识别结果写入 `logs/client_recognition/recognition_*.json`。如果没有最终识别结果，不生成空日志。

## 配置

服务端环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CLOUD_STT_HOST` | `0.0.0.0` | 服务监听地址 |
| `CLOUD_STT_PORT` | `8000` | 服务监听端口 |
| `DOUBAO_ASR_API_KEY` | 无 | 火山引擎新版控制台 API Key；也可用 `DOUBAO_ASR_APP_KEY` + `DOUBAO_ASR_ACCESS_KEY` |
| `DOUBAO_ASR_RESOURCE_ID` | `volc.seedasr.sauc.duration` | 豆包流式语音识别模型 2.0 小时版；并发版用 `volc.seedasr.sauc.concurrent` |
| `DOUBAO_ASR_LANGUAGE` | 未设置 | 默认不传，使用中文默认模型能力，覆盖普通话和主流中文方言 |
| `DOUBAO_ASR_ENABLE_NONSTREAM` | `true` | 开启二遍识别，提升分句最终结果质量 |
| `DASHSCOPE_API_KEY` | 无 | 可选：仅当 `asr.provider=dashscope` 时使用 |
| `FSMN_VAD_MODEL` | `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch` | FSMN-VAD 模型名或本地路径 |

客户端常用参数：

| 参数 | 说明 |
| --- | --- |
| `--server` | 服务端 HTTP 地址，必须包含端口 |
| `--websocket-url` | 可选 WebSocket 公网地址，客户端会自动追加 session_id |
| `--wake-word` | 开启本地唤醒词模式 |
| `--wake-word-idle-timeout-seconds` | 唤醒后空闲超时，默认 60 秒 |
| `--wake-word-interrupt-texts` | 本地中断词，默认 `退出 停下 停止 结束` |
| `--audio-format` | `pcm_s16le` 或 `opus` |
| `--timing` | 输出客户端耗时事件 |
| `--recognition-log-dir` | 客户端识别日志目录，默认 `logs/client_recognition` |
| `--disable-recognition-log` | 关闭客户端识别日志 |

## 机器人端接入

机器人端不需要使用完整客户端，可直接实现 HTTP + WebSocket 协议。推荐先用 `pcm_s16le`：

```text
sample_rate = 16000
channels = 1
frame_duration_ms = 20
frame_bytes = 640
```

详细协议见 [docs/robot_integration_api.md](docs/robot_integration_api.md)。

## 测试

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests -q -p no:cacheprovider
```

如果本机未安装测试依赖：

```powershell
python -m pip install -e ".[dev]"
```
