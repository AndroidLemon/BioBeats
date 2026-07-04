# Tee generated audio to a WAV file while still playing it.
#
# RecordingAudioSink is an AudioSinkProtocol decorator: start()/write()/stop()
# forward to the wrapped sink AND capture the audio to a 16-bit PCM WAV, so you
# can keep a take. Pure composition — drops in front of the real AudioSink (or
# NullAudioSink) with no changes to the engine. wave is stdlib, so this stays
# import-clean on CI.

import wave

import numpy as np

from src.output.audio_sink import CHANNELS, SAMPLE_RATE, AudioSinkProtocol


class RecordingAudioSink:
    """AudioSinkProtocol decorator that writes a WAV alongside playback.

    The WAV file spans start() -> stop(): start() opens it, write() appends the
    chunk (converted to 16-bit PCM) and forwards it to the inner sink, stop()
    closes it. Format defaults match the engine's output (48 kHz stereo).
    """

    def __init__(
        self,
        inner: AudioSinkProtocol,
        path,
        *,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
    ) -> None:
        self._inner = inner
        self._path = str(path)
        self._sample_rate = sample_rate
        self._channels = channels
        self._wav: wave.Wave_write | None = None

    def start(self) -> None:
        """Open the WAV (16-bit PCM) and start the inner sink."""
        wav = wave.open(self._path, "wb")
        wav.setnchannels(self._channels)
        wav.setsampwidth(2)  # 16-bit PCM
        wav.setframerate(self._sample_rate)
        self._wav = wav
        try:
            self._inner.start()
        except Exception:
            # Don't leave a dangling/partial WAV if the device fails to open.
            self._wav = None
            wav.close()
            raise

    def write(self, samples: np.ndarray) -> None:
        """Append the chunk to the WAV, then forward it to the inner sink."""
        if self._wav is not None:
            self._wav.writeframes(self._to_pcm16(samples))
        self._inner.write(samples)

    def buffered_frames(self) -> int:
        """Forward to the inner sink (recording adds no playback queue)."""
        return self._inner.buffered_frames()

    def underruns(self) -> int:
        """Forward to the inner sink."""
        return self._inner.underruns()

    def stop(self) -> None:
        """Stop the inner sink and close the WAV. The WAV is always finalized."""
        try:
            self._inner.stop()
        finally:
            # Close in finally so the WAV header is flushed even if stop() raises.
            if self._wav is not None:
                self._wav.close()
                self._wav = None

    @staticmethod
    def _to_pcm16(samples: np.ndarray) -> bytes:
        """Convert (N, channels) float32 in [-1, 1] to interleaved 16-bit PCM bytes."""
        arr = np.asarray(samples, dtype=np.float32)
        clipped = np.clip(arr, -1.0, 1.0)
        return (clipped * 32767.0).astype("<i2").tobytes()
