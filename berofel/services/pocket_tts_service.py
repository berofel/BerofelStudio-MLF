"""Deprecated compatibility import for projects upgraded from Pocket TTS.

Pocket TTS is not an available synthesis backend. Existing rendered audio and
project media remain usable; new requests are delegated to the single Qwen
Base narration service.
"""
from .narration_service import (LANGUAGES, NarrationRequest, _process_flags,
    generate_narration, persistent_folder, validate_request)

__all__ = ['LANGUAGES','NarrationRequest','generate_narration',
           'persistent_folder','validate_request']
