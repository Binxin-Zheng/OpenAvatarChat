# OpenAvatarChat Project Structure

## 1. Service Startup Flow

```
demo.py (entry point)
    |
    +-- parse_args()          --> --host, --port, --config, --env
    |
    +-- load_config()         --> Dynaconf YAML loading
    |   +-- logger_config          (log_level, etc.)
    |   +-- service_config         (host, port, SSL certs)
    |   +-- chat_engine_config     (handlers, outputs, model_root)
    |
    +-- setup_logging()
    |
    +-- ChatEngine()
    |   +-- HandlerManager.register_handlers()
    |   |   +-- scan handler_search_path ("src/handlers")
    |   |   +-- importlib.import_module(each handler module)
    |   |   +-- inspect -> find HandlerBase subclass
    |   |   +-- validate config, store HandlerRegistry
    |   |
    |   +-- HandlerManager.load_handlers()
    |       +-- handler.load(engine_config, handler_config)
    |       +-- client_handler.on_setup_app(gradio_app)
    |
    +-- setup_ssl_context()
    |
    +-- Uvicorn.run(gradio_app)   --> HTTPS server live
```

## 2. Overall Architecture

```
+---------------------------------------------------------------------+
|                         Uvicorn + Gradio                             |
|                     (HTTPS / WebSocket server)                      |
+-----------------------------+---------------------------------------+
                              |
                     +--------v--------+
                     |   ChatEngine    |
                     |  (Orchestrator) |
                     +--------+--------+
                              |
               +--------------+--------------+
               |              |              |
      +--------v---+  +------v------+  +---v----------+
      |  Handler   |  |   Session   |  |  RTC Service  |
      |  Manager   |  |   Manager   |  |  (TURN/ICE)   |
      +--------+---+  +------+------+  +---+----------+
               |              |              |
    +----------+       +-----v-----+        |
    | Discovers &      |ChatSession|<-------+
    | loads all        | (per user)|
    | handlers         +-----+-----+
    |                        |
    |             +----------+-------------+
    v             v          v             v
 +------+  +----------+ +--------+ +-----------+
 |Client|  | Pipeline | | Queues | |  Shared   |
 |Handler| | Handlers | |(in/out)| |  States   |
 +------+  +----------+ +--------+ +-----------+
```

## 3. Handler Pipeline (Data Flow)

This is the core - how audio/video flows through handlers:

```
  Browser (WebRTC)
       |
       |  mic audio + camera video
       v
+--------------+
|  RtcStream   |  (fastrtc AsyncAudioVideoStreamHandler)
|  (per user)  |
+------+-------+
       | puts raw frames into session input_queues
       v
+------------------------------------------------------------------+
|                     ChatSession Pipeline                          |
|                                                                   |
|  +--------------------------------------------------------------+ |
|  |              Input Pump (background thread)                  | |
|  |  reads input_queues -> wraps as ChatData -> distribute_data()| |
|  +---------------------------+----------------------------------+ |
|                              |                                    |
|         +--------------------+---------------------+              |
|         | MIC_AUDIO          | CAMERA_VIDEO         | TEXT        |
|         v                    v                      v             |
|  +------------+      (passed to LLM        (not commonly used)   |
|  | SileroVAD  |       if multimodal)                              |
|  |            |                                                   |
|  | States:    |                                                   |
|  | PRE_START  |                                                   |
|  | -> START   |                                                   |
|  | -> END     |                                                   |
|  +-----+------+                                                   |
|        | HUMAN_AUDIO (segmented speech chunks)                    |
|        v                                                          |
|  +------------+                                                   |
|  | SenseVoice |  (ASR)                                            |
|  |            |                                                   |
|  +-----+------+                                                   |
|        | HUMAN_TEXT                                                |
|        v                                                          |
|  +---------------------+                                          |
|  | LLM (OpenAI compat) |                                         |
|  | Qwen / Dify / etc.  |                                         |
|  |                      |                                         |
|  | chat history mgmt    |                                         |
|  +-----+----------------+                                         |
|        | AVATAR_TEXT (streaming tokens)                            |
|        v                                                          |
|  +------------+                                                   |
|  | TTS Engine |  (CosyVoice / EdgeTTS / Bailian)                 |
|  |            |                                                   |
|  +-----+------+                                                   |
|        | AVATAR_AUDIO                                             |
|        v                                                          |
|  +----------------+                                               |
|  | Avatar Engine  |  (LiteAvatar / MuseTalk / LAM)               |
|  |                |                                               |
|  | audio -> face  |                                               |
|  | animation      |                                               |
|  +--+----------+--+                                               |
|     |          |                                                  |
|     | AVATAR_  | AVATAR_                                          |
|     | AUDIO    | VIDEO                                            |
|     v          v                                                  |
|  +------------------+                                             |
|  |  Output Queues   |  (session_context.output_queues)            |
|  +--------+---------+                                             |
+-----------+-----------------------------------------------------------+
            |
            v
     +--------------+
     |  RtcStream   |  H.264 encode (HW->SW fallback)
     |  (output)    |
     +------+-------+
            |  WebRTC audio + video
            v
        Browser
```

## 4. Handler Registration & Discovery

```
config YAML                          src/handlers/
---------------                      --------------
handler_configs:                     +-- asr/
  SileroVad:                         |   +-- sensevoice/
    module: vad/silerovad/...   --+  |       +-- asr_handler_sensevoice.py
  SenseVoice:                     |  +-- vad/
    module: asr/sensevoice/...    |  |   +-- silerovad/
  LLMOpenAI:                      |  |       +-- vad_handler_silero.py
    module: llm/openai_.../...    |  +-- llm/
  CosyVoice:                      |  |   +-- openai_compatible/
    module: tts/cosyvoice/...     |  |   +-- dify/
  LiteAvatar:                     |  +-- tts/
    module: avatar/liteavatar/... |  |   +-- cosyvoice/
                                  |  |   +-- edgetts/
         HandlerManager           |  |   +-- bailian_tts/
        +-------------+           |  +-- avatar/
        | For each     |<---------+      +-- liteavatar/
        | config entry:|                  +-- musetalk/
        |              |                  +-- lam/
        | 1. importlib |
        |    .import() |-->  loads .py module
        |              |
        | 2. inspect   |-->  finds class(HandlerBase)
        |    .getmembers|
        |              |
        | 3. validate  |-->  config_model.validate(yaml_config)
        |    config    |
        |              |
        | 4. register  |-->  HandlerRegistry(info, handler, config)
        |              |
        | 5. load()    |-->  handler downloads models, inits GPU
        +-------------+
```

## 5. Per-Session Data Routing

```
                    ChatSession
                    +------------------------------------------------+
                    |                                                 |
                    |  DataSource/DataSink mapping:                   |
                    |                                                 |
                    |   source(MIC_AUDIO) --sink--> SileroVAD        |
                    |   source(CAMERA_VIDEO) -sink-> LLM (optional)  |
                    |                                                 |
                    |  Handler outputs route to next handler's sink:  |
                    |                                                 |
                    |   VAD.output(HUMAN_AUDIO) ----> ASR.input       |
                    |   ASR.output(HUMAN_TEXT)  ----> LLM.input       |
                    |   LLM.output(AVATAR_TEXT) ----> TTS.input       |
                    |   TTS.output(AVATAR_AUDIO)--> Avatar.input      |
                    |                                                 |
                    |  Final outputs (configured in YAML "outputs"):  |
                    |                                                 |
                    |   Avatar.output(AVATAR_VIDEO) -> output_queue   |
                    |   Avatar.output(AVATAR_AUDIO) -> output_queue   |
                    |   LLM.output(AVATAR_TEXT)     -> output_queue   |
                    |                                                 |
                    |  Each handler runs in its own thread            |
                    |  ("handler pumper"), reading from its           |
                    |  input queue and writing to distribute_data()   |
                    +------------------------------------------------+
```

## 6. ChatData Type System

```
ChatDataType enum (what flows between handlers):

  Client -> Engine:              Engine internal:           Engine -> Client:
  +----------------+    +----------------------+    +------------------+
  | MIC_AUDIO      |--->| HUMAN_AUDIO (VAD out)|    | AVATAR_TEXT      |
  | CAMERA_VIDEO   |    | HUMAN_TEXT  (ASR out) |--->| AVATAR_AUDIO     |
  |                |    | AVATAR_TEXT (LLM out) |    | AVATAR_VIDEO     |
  |                |    | HUMAN_VOICE_ACTIVITY  |    |                  |
  +----------------+    +----------------------+    +------------------+

Each ChatData wraps a DataBundle:
+---------------------------------+
| ChatData                        |
|  +-- source: "SileroVAD"       |
|  +-- type: HUMAN_AUDIO          |
|  +-- timestamp: (48000, 16000)  |
|  +-- data: DataBundle           |
|       +-- definition (schema)   |
|       +-- metadata {}           |
|       +-- events []             |
|       +-- data [ndarray/str]    |
+---------------------------------+
```

## 7. Key Files Reference

| File Path | Purpose |
|-----------|---------|
| `src/demo.py` | Main entry point, server initialization |
| `src/chat_engine/chat_engine.py` | Core engine, session management |
| `src/chat_engine/core/handler_manager.py` | Dynamic handler discovery & registration |
| `src/chat_engine/core/chat_session.py` | Session execution, data pipeline |
| `src/chat_engine/common/handler_base.py` | Handler interface definition |
| `src/chat_engine/common/client_handler_base.py` | Client handler abstract base |
| `src/chat_engine/contexts/session_context.py` | Per-session state, queues, timestamps |
| `src/chat_engine/contexts/handler_context.py` | Per-handler context within a session |
| `src/chat_engine/data_models/chat_engine_config_data.py` | Configuration schemas |
| `src/chat_engine/data_models/runtime_data/data_bundle.py` | Data container & definitions |
| `src/chat_engine/data_models/chat_data_type.py` | ChatDataType enum |
| `src/service/service_utils/service_config_loader.py` | YAML config loading via Dynaconf |
| `src/service/rtc_service/rtc_provider.py` | RTC/TURN setup (singleton) |
| `src/service/rtc_service/rtc_stream.py` | WebRTC stream handling |
| `src/handlers/client/rtc_client/client_handler_rtc.py` | RTC client + H.264 HW encoding |

## 8. Key Takeaways

- **Plugin architecture**: Handlers are discovered at runtime from `src/handlers/` via `importlib` + `inspect`. Adding a new handler = add a folder + update YAML config.
- **Queue-based pipeline**: Each handler has its own input queue and runs in a dedicated thread. Data routing is based on `ChatDataType` matching between handler outputs and the next handler's expected inputs.
- **Per-session isolation**: Each WebRTC connection spawns a `ChatSession` with its own queues, handler contexts, and shared states.
- **Config-driven composition**: Which handlers are active, their parameters, and the final output mapping are all controlled by YAML - no code changes needed to swap ASR/LLM/TTS/Avatar implementations.
- **WebRTC with HW acceleration**: The RTC layer supports H.264 hardware encoding (NVENC, QSV, VideoToolbox) with automatic fallback to software encoding.
