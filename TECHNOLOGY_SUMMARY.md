# Open Avatar Chat - Technology Summary

## What It Is

Open Avatar Chat is an open-source framework that creates **real-time, interactive digital humans** — virtual avatars that can see, hear, understand, and speak back to users through a web browser. A user opens a webpage, speaks naturally, and a lifelike avatar responds with synchronized lip movement, facial expressions, and voice — all in real time, with an average end-to-end latency of around 2 seconds.

The project is developed by the HumanAIGC Engineering Team. Its 3D avatar component (LAM) was accepted at **SIGGRAPH 2025**, the premier venue for computer graphics research.

---

## Why It Matters

| Challenge | How Open Avatar Chat Addresses It |
|---|---|
| Digital humans typically require expensive proprietary platforms | Fully open-source; runs on a single PC with a consumer GPU |
| Building a real-time avatar system means stitching together many AI models | Modular pipeline — swap any component (speech recognition, language model, voice synthesis, avatar) via a config file, no code changes |
| Low latency is critical for natural conversation | ~2.2s voice-to-voice latency on commodity hardware (RTX 4090), including network round-trip |
| Deploying to users is complex | Browser-based — users need only a web link; no app installation required |

This makes it practical for **education** (AI tutors with a human face), **customer service** (multilingual virtual agents), **accessibility** (conversational interfaces for users who struggle with text), and **research** (a testbed for multimodal AI interaction).

---

## How It Works

The system is a **pipeline of specialized AI handlers**, each responsible for one stage of the conversation loop:

```
User speaks into microphone
        |
        v
  [Voice Activity Detection]  — Silero VAD detects when the user starts/stops speaking
        |
        v
  [Speech Recognition (ASR)]  — SenseVoice converts speech to text
        |
        v
  [Language Model (LLM)]      — Qwen, GPT, Gemini, or a local model generates a response
        |
        v
  [Text-to-Speech (TTS)]      — CosyVoice or Edge TTS synthesizes natural speech
        |
        v
  [Avatar Rendering]           — Audio drives facial animation on a 2D or 3D avatar
        |
        v
  [WebRTC Streaming]           — H.264 video streamed to the user's browser in real time
```

An alternative path supports **multimodal models** like Qwen-Omni that accept audio and video natively and produce speech directly, bypassing the separate ASR and TTS stages for even lower latency.

---

## Key Technical Components

### Modular Handler Architecture

Every stage in the pipeline is a pluggable **handler** — a Python class that declares its input/output data types. The engine discovers handlers at runtime, wires them together based on a YAML configuration file, and manages per-user sessions with isolated queues. Adding a new ASR engine or avatar renderer means implementing a single interface and writing a config entry.

### Avatar Technologies (Three Options)

| Avatar | Type | Technique | Strength |
|---|---|---|---|
| **LiteAvatar** | 2D | Expression-driven animation from 150+ pre-built character models | Lightweight, runs on CPU or GPU, multi-session on one GPU |
| **MuseTalk** | 2D | Video-to-video lip-sync synthesis from any base footage | Custom appearance from a single video clip |
| **LAM** | 3D | Audio-to-ARKit-blendshape mapping via Wav2Vec2; rendered in browser WebGL | Photorealistic 3D face from a single photo (SIGGRAPH 2025) |

### Real-Time Communication

The system uses **WebRTC** for bidirectional audio/video streaming between the server and the browser. Video frames are encoded with **hardware-accelerated H.264** (NVIDIA NVENC, Intel Quick Sync, or software fallback) at up to 2.5 Mbps with zero-latency tuning. A TURN/STUN server layer handles NAT traversal for deployment across networks.

### Supported AI Backends

The framework is backend-agnostic. Current integrations include:

- **Speech Recognition:** SenseVoice (Alibaba/FunASR)
- **Language Models:** Any OpenAI-compatible API (Qwen, GPT, Gemini, Ollama), Qwen-Omni (native multimodal), MiniCPM (local), Dify (workflow platform)
- **Voice Synthesis:** CosyVoice (local or API, with voice cloning), Microsoft Edge TTS, Qwen-TTS
- **Multimodal:** Camera video can be fed alongside audio to vision-language models for visual understanding

---

## Architecture at a Glance

```
                    ┌──────────────────────────────────┐
                    │           Web Browser             │
                    │  (WebRTC audio/video + WebSocket) │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │     FastAPI + Gradio Server       │
                    │     (HTTPS, SSL/TLS, TURN)        │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │         Chat Engine               │
                    │  ┌─────────────────────────────┐  │
                    │  │   Session Manager            │  │
                    │  │   (per-user isolated queues)  │  │
                    │  └──────────┬──────────────────┘  │
                    │             │                      │
                    │  ┌──────── ▼ ─── Handler Pipeline ─────────┐  │
                    │  │  VAD → ASR → LLM → TTS → Avatar        │  │
                    │  │         (or Multimodal LLM → Avatar)    │  │
                    │  └─────────────────────────────────────────┘  │
                    └──────────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │     GPU / Cloud API Backends      │
                    │  (PyTorch, CUDA, Model Hub APIs)  │
                    └──────────────────────────────────┘
```

---

## Infrastructure & Deployment

- **Runtime:** Python 3.11, PyTorch 2.8, CUDA 12.8
- **Package management:** `uv` (installs only the dependencies needed for the selected configuration)
- **Containerization:** Docker & Docker Compose support for reproducible deployment
- **Hardware encoding:** Automatic detection of GPU video encoders (NVENC/QSV) with CPU fallback
- **Scalability:** Per-session isolation allows concurrent users; LiteAvatar supports multiple sessions per GPU

---

## Performance

On a test machine with an Intel i9-13900KF and NVIDIA RTX 4090:

- **End-to-end voice latency:** ~2.2 seconds (includes network round-trip, VAD silence detection, and full pipeline computation)
- **Avatar rendering:** 25-30 FPS
- **Video bitrate:** 0.5-2.5 Mbps adaptive

The cloud API configuration (offloading ASR/LLM/TTS to hosted services) significantly reduces local GPU requirements, making deployment feasible on machines without high-end GPUs.

---

## Summary

Open Avatar Chat combines state-of-the-art speech AI, large language models, and real-time avatar rendering into a single, modular, open-source system. Its plug-and-play architecture means researchers can experiment with new models without re-engineering the pipeline, while its browser-based delivery makes it immediately accessible to end users. The inclusion of SIGGRAPH-published 3D avatar technology (LAM) alongside practical 2D alternatives provides flexibility across use cases — from lightweight educational assistants to photorealistic virtual humans.
