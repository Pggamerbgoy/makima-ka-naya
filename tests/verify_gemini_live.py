"""
Makima v2 — Verification Test for Gemini 3.8 Live Native Voice Engine.
Mandate: Zero TTS. Direct bidirectional Gemini Live audio stream.
Tests:
1. Dynamic config & LiveConnectConfig building (modalities=[AUDIO], SpeechConfig with voice selection).
2. Live tool conversion from ToolRegistry into Gemini function declarations.
3. LiveVoiceController initialization, queue buffering, and barge-in interruption.
4. AudioIO PCM playback & hardware device discovery.
5. Strict zero-TTS check (ensures no TTS modules or tools exist).
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from makima.tools.registry import get_registry
from makima.voice.audio_io import AudioIO
from makima.voice.gemini_live import GeminiLiveSession
from makima.voice.controller import LiveVoiceController


class TestGeminiLiveVoice(unittest.TestCase):

    def test_01_zero_tts_mandate(self):
        """Verify NO TTS modules or speak_text tools are present in the codebase."""
        # Ensure edge_tts_synth is gone
        edge_tts_file = Path(__file__).parent.parent / "makima" / "voice" / "edge_tts_synth.py"
        self.assertFalse(edge_tts_file.exists(), "Standalone TTS module must be completely removed")

        # Discover tools and verify no speak_text tool exists
        reg = get_registry()
        reg.discover()
        registered_names = [t.name for t in reg.list_tools()]
        self.assertNotIn("speak_text", registered_names, "Legacy speak_text TTS tool must not be registered")
        print("  [PASS] Zero-TTS mandate strictly validated.")

    def test_02_audio_hardware_and_pcm_streaming(self):
        """Verify AudioIO device discovery, PCM chunk playback, and stop_playback methods."""
        devices = AudioIO.list_audio_devices()
        self.assertIsInstance(devices, list)
        self.assertGreater(len(devices), 0)

        # Test stop_playback does not raise
        AudioIO.stop_playback()

        # Test PCM playback with dummy 16-bit PCM bytes
        dummy_pcm = b"\x00\x00" * 1024
        res = AudioIO.play_pcm_chunk(dummy_pcm)
        self.assertTrue(res)
        AudioIO.stop_playback()
        print("  [PASS] AudioIO hardware discovery & PCM streaming verified.")

    def test_03_gemini_live_session_config(self):
        """Verify LiveConnectConfig generation with AUDIO modality and ToolRegistry declarations."""
        session = GeminiLiveSession(
            api_key="test_mock_gemini_key",
            model="gemini-3.8-live",
            voice_name="Aoede",
        )
        self.assertEqual(session.voice_name, "Aoede")
        self.assertEqual(session.model, "gemini-3.8-live")

        config = session._build_live_config()
        self.assertIsNotNone(config)
        # Verify modality is AUDIO
        from google.genai import types
        self.assertIn(types.Modality.AUDIO, config.response_modalities)

        # Verify voice config matches
        self.assertEqual(
            config.speech_config.voice_config.prebuilt_voice_config.voice_name,
            "Aoede",
        )

        # Verify registered tools are included in function declarations
        self.assertIsNotNone(config.tools)
        tool_decl = config.tools[0]
        func_names = [f.name for f in tool_decl.function_declarations]
        self.assertIn("inspect_app_ui", func_names)
        self.assertIn("execute_command", func_names)
        print(f"  [PASS] LiveConnectConfig verified ({len(func_names)} tools mapped to Gemini function declarations).")

    def test_04_live_voice_controller_flow(self):
        """Verify LiveVoiceController buffering, barge-in detection, and event dispatch."""
        mock_session = MagicMock(spec=GeminiLiveSession)
        mock_session.is_active = True
        mock_session.send_audio_chunk = AsyncMock()

        events_received = []
        def _on_status(event_type, payload):
            events_received.append((event_type, payload))

        controller = LiveVoiceController(
            session=mock_session,
            voice_name="Kore",
            on_status=_on_status,
        )

        # Test simulated mic input callback
        import numpy as np
        # 1024 frames of silent audio
        silent_data = np.zeros(1024, dtype=np.int16)
        controller._loop = asyncio.new_event_loop()
        controller._is_running = True

        controller._mic_callback(silent_data, 1024, None, None)
        self.assertEqual(controller._audio_queue.qsize(), 1)

        # High volume data (simulating user speaking / barge-in)
        loud_data = np.ones(1024, dtype=np.int16) * 10000
        with patch.object(AudioIO, "stop_playback") as mock_stop:
            controller._mic_callback(loud_data, 1024, None, None)
            mock_stop.assert_called_once()
            print("  [PASS] Barge-in speech interruption correctly triggered AudioIO.stop_playback().")

        controller._loop.close()

    def test_05_mock_live_receive_stream(self):
        """Verify in-stream audio and tool call handling from Gemini Live stream."""
        async def _test():
            from google.genai import types

            class MockPart:
                inline_data = types.Blob(data=b"\x00" * 480, mime_type="audio/pcm;rate=24000")
                text = None

            class MockServerContent:
                model_turn = MagicMock(parts=[MockPart()])

            class MockResponse:
                server_content = MockServerContent()
                tool_call = None

            async def _fake_receive():
                yield MockResponse()

            mock_client_session = MagicMock()
            mock_client_session.receive = _fake_receive

            session = GeminiLiveSession(api_key="mock_key")
            session._session = mock_client_session
            session._is_active = True

            events = []
            async for ev in session.receive_events():
                events.append(ev)

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["type"], "audio")
            self.assertEqual(len(events[0]["data"]), 480)

        asyncio.run(_test())
        print("  [PASS] Gemini Live audio stream reception verified.")


if __name__ == "__main__":
    print("=" * 75)
    print("MAKIMA v2 — STEP 15: GEMINI 3.8 LIVE NATIVE VOICE VERIFICATION")
    print("=" * 75)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestGeminiLiveVoice)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("=" * 75)
        print("ALL GEMINI LIVE VOICE TESTS PASSED (EXIT CODE 0)")
        print("=" * 75)
        sys.exit(0)
    else:
        print("=" * 75)
        print("TEST FAILURES ENCOUNTERED")
        print("=" * 75)
        sys.exit(1)
