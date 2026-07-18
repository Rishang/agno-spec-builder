import unittest
from unittest.mock import Mock, patch

from agno_spec_builder.tools.openai import OpenAICompatibleTools


class _StreamingResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_bytes(self):
        yield b"first"
        yield b"second"


class OpenAICompatibleToolsTests(unittest.TestCase):
    def test_tts_forwards_base_url_and_collects_streaming_audio(self):
        create = Mock(return_value=_StreamingResponse())
        client = Mock()
        client.audio.speech.with_streaming_response.create = create

        with patch("agno_spec_builder.tools.openai.OpenAI", return_value=client) as openai:
            tools = OpenAICompatibleTools(
                api_key="key",
                base_url="https://openrouter.ai/api/v1",
                text_to_speech_model="hexgrad/kokoro-82m",
                enable_transcription=False,
                enable_image_generation=False,
            )
            events = list(tools.generate_speech(Mock(), "Hello! This is a text-to-speech test."))

        openai.assert_called_once_with(api_key="key", base_url="https://openrouter.ai/api/v1")
        create.assert_called_once_with(
            model="hexgrad/kokoro-82m",
            voice="alloy",
            input="Hello! This is a text-to-speech test.",
            response_format="mp3",
        )
        self.assertEqual([event.audio[0].content for event in events[:-1]], [b"first", b"second"])
        self.assertTrue(all(event.audio[0].mime_type == "audio/mp3" for event in events[:-1]))
        self.assertEqual(events[-1], "Speech streamed successfully.")
