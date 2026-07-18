"""OpenAI-compatible TTS toolkit for custom API base URLs such as OpenRouter."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agno.agent import Agent
from agno.media import Audio
from agno.run.agent import CustomEvent
from agno.team import Team
from agno.tools.openai import OpenAITools as _OpenAITools
from openai import OpenAI


@dataclass
class AudioChunkEvent(CustomEvent):
    """One streamed TTS audio chunk, serialized by Agno as base64."""

    audio: list[Audio] | None = None

    def __str__(self) -> str:
        # Keep binary chunks out of the tool result passed back to the model.
        return ""


class OpenAICompatibleTools(_OpenAITools):
    """Agno's OpenAI tools with streaming TTS through a custom API base URL."""

    def __init__(self, *, base_url: str, **kwargs: Any) -> None:
        self.base_url = base_url
        super().__init__(**kwargs)

    def generate_speech(self, agent: Agent | Team, text_input: str) -> Iterator[AudioChunkEvent | str]:
        """Stream TTS chunks as Agno custom events for ``agent.arun(stream=True)``."""
        with OpenAI(api_key=self.api_key, base_url=self.base_url).audio.speech.with_streaming_response.create(
            model=self.tts_model,
            voice=self.tts_voice,
            input=text_input,
            response_format=self.tts_format,
        ) as response:
            for chunk in response.iter_bytes():
                yield AudioChunkEvent(
                    audio=[Audio(id=str(uuid4()), content=chunk, mime_type=f"audio/{self.tts_format}")]
                )

