"""STT adapter layer — pluggable speech-to-text backends.

Default adapter: faster-whisper
Fallback adapter: whisper (openai-whisper)
Custom: implement the STTAdapter protocol and set stt.custom_module in config.
"""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol

from models import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)


class STTAdapter(Protocol):
    """Protocol for STT backends. Implement this to add a new backend."""

    def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
    ) -> TranscriptResult: ...


class FasterWhisperAdapter:
    """Adapter for faster-whisper (CTranslate2-based, fast local inference)."""

    def __init__(self, model: str, device: str, compute_type: str) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel  # type: ignore
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            except ImportError:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: pip install faster-whisper"
                )
        return self._model

    def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
    ) -> TranscriptResult:
        model = self._load_model()
        try:
            segments_iter, info = model.transcribe(
                audio_path,
                language=language_hint,
                beam_size=5,
                vad_filter=True,
            )
            segments: list[TranscriptSegment] = []
            transcript_parts: list[str] = []

            for seg in segments_iter:
                segments.append(
                    TranscriptSegment(start=seg.start, end=seg.end, text=seg.text)
                )
                transcript_parts.append(seg.text.strip())

            return TranscriptResult(
                transcript=" ".join(transcript_parts),
                detected_language=info.language,
                confidence=getattr(info, "language_probability", None),
                segments=segments,
            )
        except Exception as e:
            logger.error(f"faster-whisper transcription failed: {e}")
            return TranscriptResult.failed(str(e))


class WhisperAdapter:
    """Adapter for OpenAI whisper (official open-source model)."""

    def __init__(self, model: str, device: str) -> None:
        self.model_name = model
        self.device = device
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                import whisper  # type: ignore
                self._model = whisper.load_model(self.model_name, device=self.device)
            except ImportError:
                raise ImportError(
                    "whisper is not installed. Install with: pip install openai-whisper"
                )
        return self._model

    def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
    ) -> TranscriptResult:
        model = self._load_model()
        try:
            options: dict[str, Any] = {}
            if language_hint:
                options["language"] = language_hint

            result = model.transcribe(audio_path, **options)

            segments: list[TranscriptSegment] = []
            for seg in result.get("segments", []):
                segments.append(
                    TranscriptSegment(
                        start=seg["start"],
                        end=seg["end"],
                        text=seg["text"],
                    )
                )

            return TranscriptResult(
                transcript=result["text"].strip(),
                detected_language=result.get("language", "unknown"),
                confidence=None,
                segments=segments,
            )
        except Exception as e:
            logger.error(f"whisper transcription failed: {e}")
            return TranscriptResult.failed(str(e))


def get_adapter(config: Any) -> STTAdapter:
    """Create the configured STT adapter.

    Args:
        config: Config instance from config_loader

    Returns:
        An STTAdapter instance ready to use.
    """
    adapter_name = config.stt_adapter

    if adapter_name == "faster_whisper":
        return FasterWhisperAdapter(
            model=config.stt_model,
            device=config.stt_device,
            compute_type=config.get("stt.compute_type", "int8"),
        )
    elif adapter_name == "whisper":
        return WhisperAdapter(
            model=config.stt_model,
            device=config.stt_device,
        )
    elif adapter_name == "custom":
        module_path = config.get("stt.custom_module")
        if not module_path:
            raise ValueError("stt.custom_module must be set when adapter is 'custom'")
        module = importlib.import_module(module_path)
        adapter_cls = getattr(module, "CustomSTTAdapter")
        return adapter_cls()
    else:
        raise ValueError(f"Unknown STT adapter: {adapter_name}")


def transcribe(
    audio_path: str,
    config: Any,
    language_hint: str | None = None,
) -> TranscriptResult:
    """Transcribe an audio file using the configured STT backend.

    Args:
        audio_path: Path to the audio file
        config: Config instance
        language_hint: Optional language hint (e.g., "de", "zh")

    Returns:
        TranscriptResult with transcript, language, confidence, segments
    """
    if not Path(audio_path).exists():
        logger.error(f"Audio file not found: {audio_path}")
        return TranscriptResult.failed(f"Audio file not found: {audio_path}")

    adapter = get_adapter(config)
    return adapter.transcribe(audio_path, language_hint=language_hint)
