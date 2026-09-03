import os
from pathlib import Path

import soundfile as sf
from kittentts import KittenTTS as KittenModel

from config import ROOT_DIR, get_tts_voice

KITTEN_MODEL = "KittenML/kitten-tts-mini-0.8"
KITTEN_SAMPLE_RATE = 24000


class TTS:
    def __init__(self) -> None:
        self._model = KittenModel(KITTEN_MODEL)
        self._voice = str(get_tts_voice() or "Jasper").strip()
        if not self._voice:
            raise ValueError("TTS voice cannot be empty")

    def synthesize(self, text, output_file=os.path.join(ROOT_DIR, ".mp", "audio.wav")):
        text = str(text or "").strip()
        if not text:
            raise ValueError("TTS text cannot be empty")

        output_path = Path(output_file).resolve()
        mp_root = (Path(ROOT_DIR) / ".mp").resolve()
        try:
            output_path.relative_to(mp_root)
        except ValueError as exc:
            raise ValueError("TTS output must be inside the .mp directory") from exc
        output_path.parent.mkdir(parents=True, exist_ok=True)

        audio = self._model.generate(text, voice=self._voice)
        sf.write(str(output_path), audio, KITTEN_SAMPLE_RATE)
        return str(output_path)
