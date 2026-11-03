"""Efeitos sonoros curtos (whoosh, pop, clique...): síntese pura e a biblioteca de arquivos em `assets/sfx`."""

from .library import SfxNotFound, library_path, resolve_sound, write_library
from .synth import PEAK_DBFS, SAMPLE_RATE, Sound, SoundDef, library_names, sound_def, synthesize

__all__ = [
    "PEAK_DBFS",
    "SAMPLE_RATE",
    "SfxNotFound",
    "Sound",
    "SoundDef",
    "library_names",
    "library_path",
    "resolve_sound",
    "sound_def",
    "synthesize",
    "write_library",
]
