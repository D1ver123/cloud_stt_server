# 客户端说明

客户端包名为 `cloud_stt_client`，负责本地音频输入和与服务端的实时通信。

## 能力

- 枚举和选择本地输入设备。
- 记住用户显式选择的麦克风。
- 将设备原生音频转换为 `16kHz mono PCM16`。
- 支持 `pcm_s16le` 直传和 Opus 编码传输。
- 支持本地 Sherpa-ONNX 唤醒词检测。
- 唤醒后保持空闲超时窗口，窗口内可多轮识别。
- 空闲窗口内继续检测本地中断词。
- 接收服务端 `asr.start`、`stt.partial`、`stt.final`、`error` 事件。

## 唤醒词模式

唤醒前，音频只在本地用于小模型检测，不上传服务端。

唤醒后：

```text
创建云端 session
-> 连接 WebSocket
-> 设置 idle_timeout_seconds，默认 60 秒
-> 音频上传服务端，同时继续喂给本地小模型
-> 收到 stt.final 后保持连接
-> 每次 stt.partial / stt.final 都刷新空闲截止时间
-> 中断词或连续空闲超时后关闭连接
-> 回到唤醒监听
```

默认中断词：

```text
退出
停下
停止
结束
```

本地关键词配置在：

```text
models/wake_word/keywords.txt
```

## 常用命令

首次在本地源码目录运行客户端前，先安装项目：

```powershell
cd "D:\myproject\pythonProject\cloud-stt"
python -m pip install -e ".[audio,wake-word,opus]"
```

如果没有安装，`python -m cloud_stt_client.cli ...` 会报 `ModuleNotFoundError: No module named 'cloud_stt_client'`。临时调试也可以使用：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

列出输入设备：

```powershell
python -m cloud_stt_client.cli list-devices
```

使用唤醒词连接云端服务：

```powershell
python -m cloud_stt_client.cli stream `
  --server http://服务器IP:8000 `
  --websocket-url ws://服务器IP:8000/stt/v1/stream `
  --wake-word `
  --wake-word-idle-timeout-seconds 60 `
  --audio-format pcm_s16le `
  --timing
```

直接推流，不等待唤醒：

```powershell
python -m cloud_stt_client.cli stream `
  --server http://服务器IP:8000 `
  --audio-format pcm_s16le `
  --duration 20
```

WAV 文件推流：

```powershell
python -m cloud_stt_client.cli stream-wav .\sample.wav `
  --server http://服务器IP:8000 `
  --audio-format pcm_s16le `
  --realtime
```

## 地址配置

`--server` 是 REST 地址，用于创建 session。

`--websocket-url` 是可选 WebSocket 地址，用于云服务器、反向代理、公网地址和内网地址不一致的场景。客户端会自动追加当前 `session_id`。

示例：

```powershell
--server http://公网IP:8000
--websocket-url ws://公网IP:8000/stt/v1/stream
```

如果不写端口，HTTP 默认访问 80，WebSocket 默认访问 80/443。服务端不在默认端口时必须显式写端口。

## 客户端事件

```json
{"type":"wake_word.detected","text":"你好小旭"}
{"type":"wake_word.interrupted","text":"停下"}
{"type":"client.timing","stage":"first_audio_sent","elapsed_ms":123.45}
```

服务端事件会原样打印：

```json
{"type":"asr.start","provider":"dashscope"}
{"type":"stt.partial","text":"向前"}
{"type":"stt.final","text":"向前走","intent":{}}
{"type":"error","message":"error detail"}
```
