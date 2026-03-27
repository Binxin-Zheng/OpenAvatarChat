import base64
import os
import re
import threading
from typing import Dict, Optional, cast

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field
from abc import ABC

from chat_engine.contexts.handler_context import HandlerContext
from chat_engine.data_models.chat_engine_config_data import ChatEngineConfigModel, HandlerBaseConfigModel
from chat_engine.common.handler_base import HandlerBase, HandlerBaseInfo, HandlerDataInfo, HandlerDetail
from chat_engine.data_models.chat_data.chat_data_model import ChatData
from chat_engine.data_models.chat_data_type import ChatDataType
from chat_engine.contexts.session_context import SessionContext
from chat_engine.data_models.runtime_data.data_bundle import DataBundle, DataBundleDefinition, DataBundleEntry
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback, AudioFormat
import dashscope


class QwenTTSConfig(HandlerBaseConfigModel, BaseModel):
    voice: str = Field(default="Cherry")
    sample_rate: int = Field(default=24000)
    api_key: str = Field(default=os.getenv("DASHSCOPE_API_KEY"))
    model_name: str = Field(default="qwen3-tts-flash-realtime")


class QwenTTSContext(HandlerContext):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.tts_client: Optional[QwenTtsRealtime] = None
        self.callback: Optional[QwenTTSCallback] = None
        self.input_text = ''


class QwenTTSCallback(QwenTtsRealtimeCallback):
    def __init__(self, context: QwenTTSContext, output_definition, speech_id: str):
        self.context = context
        self.output_definition = output_definition
        self.speech_id = speech_id
        self.temp_bytes = b''
        self.complete_event = threading.Event()
        self.error_occurred = False

    def on_open(self) -> None:
        logger.info('Qwen TTS connection opened')

    def on_close(self, close_status_code, close_msg) -> None:
        logger.info(f'Qwen TTS connection closed: {close_status_code}')
        self.complete_event.set()

    def on_event(self, response: str) -> None:
        try:
            resp_type = response.get('type', '')
            if resp_type == 'session.created':
                session_id = response.get('session', {}).get('id', '')
                logger.info(f'Qwen TTS session created: {session_id}')
            elif resp_type == 'response.audio.delta':
                audio_b64 = response.get('delta', '')
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    self.temp_bytes += audio_bytes
                    if len(self.temp_bytes) > 24000:
                        self._submit_audio(speech_end=False)
            elif resp_type == 'response.done':
                logger.info('Qwen TTS response done')
                if len(self.temp_bytes) > 0:
                    self._submit_audio(speech_end=False)
                self.send_speech_end()
                self.complete_event.set()
            elif resp_type == 'session.finished':
                logger.info('Qwen TTS session finished')
                self.complete_event.set()
            elif resp_type == 'error':
                error_msg = response.get('error', {}).get('message', 'unknown error')
                logger.error(f'Qwen TTS error: {error_msg}')
                self.error_occurred = True
                self.complete_event.set()
        except Exception as e:
            logger.error(f'Qwen TTS callback error: {e}')
            self.error_occurred = True
            self.complete_event.set()

    def _submit_audio(self, speech_end: bool):
        if len(self.temp_bytes) == 0 and not speech_end:
            return
        if len(self.temp_bytes) > 0:
            output_audio = np.frombuffer(self.temp_bytes, dtype=np.int16).astype(np.float32) / 32767
            output_audio = output_audio[np.newaxis, ...]
        else:
            output_audio = np.zeros(shape=(1, 240), dtype=np.float32)
        output = DataBundle(self.output_definition)
        output.set_main_data(output_audio)
        output.add_meta("avatar_speech_end", speech_end)
        output.add_meta("speech_id", self.speech_id)
        self.context.submit_data(output)
        self.temp_bytes = b''

    def send_speech_end(self):
        output = DataBundle(self.output_definition)
        output.set_main_data(np.zeros(shape=(1, 240), dtype=np.float32))
        output.add_meta("avatar_speech_end", True)
        output.add_meta("speech_id", self.speech_id)
        self.context.submit_data(output)

    def wait_for_complete(self, timeout: float = 30.0) -> bool:
        return self.complete_event.wait(timeout=timeout)


class HandlerTTS(HandlerBase, ABC):
    def __init__(self):
        super().__init__()
        self.voice = None
        self.sample_rate = None
        self.model_name = None

    def get_handler_info(self) -> HandlerBaseInfo:
        return HandlerBaseInfo(
            config_model=QwenTTSConfig,
        )

    def get_handler_detail(self, session_context: SessionContext,
                           context: HandlerContext) -> HandlerDetail:
        definition = DataBundleDefinition()
        definition.add_entry(DataBundleEntry.create_audio_entry("avatar_audio", 1, self.sample_rate))
        inputs = {
            ChatDataType.AVATAR_TEXT: HandlerDataInfo(
                type=ChatDataType.AVATAR_TEXT,
            )
        }
        outputs = {
            ChatDataType.AVATAR_AUDIO: HandlerDataInfo(
                type=ChatDataType.AVATAR_AUDIO,
                definition=definition,
            )
        }
        return HandlerDetail(inputs=inputs, outputs=outputs)

    def load(self, engine_config: ChatEngineConfigModel, handler_config: Optional[BaseModel] = None):
        config = cast(QwenTTSConfig, handler_config)
        self.voice = config.voice
        self.sample_rate = config.sample_rate
        self.model_name = config.model_name
        if 'DASHSCOPE_API_KEY' in os.environ:
            dashscope.api_key = os.environ['DASHSCOPE_API_KEY']
        else:
            dashscope.api_key = config.api_key

    def create_context(self, session_context, handler_config=None):
        context = QwenTTSContext(session_context.session_info.session_id)
        return context

    def start_context(self, session_context, context: HandlerContext):
        pass

    def _create_tts_client(self, context: QwenTTSContext, output_definition, speech_id: str):
        callback = QwenTTSCallback(
            context=context, output_definition=output_definition, speech_id=speech_id)
        context.callback = callback
        client = QwenTtsRealtime(
            model=self.model_name,
            callback=callback,
            url='wss://dashscope.aliyuncs.com/api-ws/v1/realtime',
        )
        client.connect()
        client.update_session(
            voice=self.voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode='server_commit',
        )
        context.tts_client = client
        return client

    def _close_tts_client(self, context: QwenTTSContext, wait: bool = True):
        if context.tts_client is not None:
            try:
                context.tts_client.finish()
                if wait and context.callback is not None:
                    context.callback.wait_for_complete(timeout=30.0)
            except Exception as e:
                logger.warning(f'Error closing Qwen TTS client: {e}')
            context.tts_client = None
            context.callback = None

    def handle(self, context: HandlerContext, inputs: ChatData,
               output_definitions: Dict[ChatDataType, HandlerDataInfo]):
        output_definition = output_definitions.get(ChatDataType.AVATAR_AUDIO).definition
        context = cast(QwenTTSContext, context)
        if inputs.type != ChatDataType.AVATAR_TEXT:
            return

        text = inputs.data.get_main_data()
        speech_id = inputs.data.get_meta("speech_id")
        if speech_id is None:
            speech_id = context.session_id

        if text is not None:
            text = re.sub(r"<\|.*?\|>", "", text)

        text_end = inputs.data.get_meta("avatar_text_end", False)
        try:
            if not text_end:
                if context.tts_client is None:
                    self._create_tts_client(context, output_definition, speech_id)
                if text:
                    logger.info(f'Qwen TTS append_text: {text}')
                    context.tts_client.append_text(text)
            else:
                if context.tts_client is None:
                    self._create_tts_client(context, output_definition, speech_id)
                if text:
                    logger.info(f'Qwen TTS append_text last: {text}')
                    context.tts_client.append_text(text)
                self._close_tts_client(context, wait=True)
                context.input_text = ''
        except Exception as e:
            logger.error(f'Qwen TTS error: {e}')
            try:
                self._close_tts_client(context, wait=False)
            except Exception as e2:
                logger.warning(f'Qwen TTS cleanup failed: {e2}')
            context.tts_client = None
            context.callback = None
            # Send end-of-speech signal so downstream doesn't hang
            output = DataBundle(output_definition)
            output.set_main_data(np.zeros(shape=(1, 240), dtype=np.float32))
            output.add_meta("avatar_speech_end", True)
            output.add_meta("speech_id", speech_id)
            context.submit_data(output)

    def destroy_context(self, context: HandlerContext):
        context = cast(QwenTTSContext, context)
        if context.tts_client is not None:
            try:
                self._close_tts_client(context, wait=False)
            except Exception:
                pass
        logger.info('Qwen TTS context destroyed')
