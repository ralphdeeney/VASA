"""CPU speech providers; native models are loaded once, never per call."""

from vasa.speech.deepgram import DeepgramTTS
from vasa.speech.kitten import KittenMicroTTS
from vasa.speech.kokoro import KokoroInt8TTS
from vasa.speech.models import SpeechModels
from vasa.speech.recognition import SherpaSTT
from vasa.speech.speechify import SpeechifyTTS
from vasa.speech.synthesis import PiperTTS, SherpaTTS

__all__ = [
    "DeepgramTTS",
    "KittenMicroTTS",
    "KokoroInt8TTS",
    "PiperTTS",
    "SherpaSTT",
    "SherpaTTS",
    "SpeechModels",
    "SpeechifyTTS",
]
