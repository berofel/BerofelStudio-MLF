from __future__ import annotations

import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from berofel.services.voice_intelligence.speaker_fingerprint import (
    VECTOR_DIMENSION, cosine_similarity, read_purec_xvector,
)


class PureCSpeakerFingerprintTests(unittest.TestCase):
    def _write(self, path: Path, values):
        path.write_bytes(struct.pack(f"<{len(values)}f", *values))

    def test_reads_only_exact_little_endian_profile_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voice.bin"
            self._write(path, [1.0] + [0.0] * (VECTOR_DIMENSION - 1))
            vector = read_purec_xvector(path)
            self.assertEqual(len(vector), VECTOR_DIMENSION)
            self.assertEqual(vector[0], 1.0)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "esperado"):
                read_purec_xvector(path)

    def test_rejects_nonfinite_and_zero_vectors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voice.bin"
            self._write(path, [float("nan")] + [0.0] * (VECTOR_DIMENSION - 1))
            with self.assertRaisesRegex(ValueError, "NaN"):
                read_purec_xvector(path)
            self._write(path, [0.0] * VECTOR_DIMENSION)
            with self.assertRaisesRegex(ValueError, "norma"):
                read_purec_xvector(path)

    def test_cosine_is_bounded_and_rejects_bad_dimensions(self):
        self.assertAlmostEqual(cosine_similarity((1.0, 0.0), (3.0, 0.0)), 1.0)
        self.assertAlmostEqual(cosine_similarity((1.0, 0.0), (-3.0, 0.0)), -1.0)
        with self.assertRaisesRegex(ValueError, "dimensões"):
            cosine_similarity((1.0,), (1.0, 0.0))
        with self.assertRaisesRegex(ValueError, "zero"):
            cosine_similarity((0.0, 0.0), (1.0, 0.0))
        with self.assertRaisesRegex(ValueError, "infinito"):
            cosine_similarity((math.inf,), (1.0,))

    def test_diagnostic_restores_exact_resident_voice_and_style(self):
        from berofel.services import qwen3_purec_tts as purec
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / "reference.wav"
            generated = root / "generated.wav"
            style = root / "style.wav"
            previous = root / "previous.bin"
            vectors = root / "cache"
            for path in (reference, generated, style, previous):
                path.write_bytes(b"valid test fixture")
            self._write(vectors, [1.0] + [0.0] * (VECTOR_DIMENSION - 1))
            generated_vector = root / "generated.bin"
            self._write(generated_vector, [0.8, 0.6] + [0.0] * (VECTOR_DIMENSION - 2))
            profile_results = iter((
                {"path": str(generated_vector), "cache_hit": False},
                {"path": str(vectors), "cache_hit": True},
            ))
            process = Mock()
            process.poll.return_value = None
            with patch.object(purec, "_PROCESS", process), \
                 patch.object(purec, "_ACTIVE_PROFILE_PATH", str(previous)), \
                 patch.object(purec, "_ACTIVE_STYLE_PATH", str(style)), \
                 patch.object(purec, "_ACTIVE_STYLE_TEXT", "texto revisado"), \
                 patch.object(purec, "_ACTIVE_ENGINE", purec.ENGINE_INT8_ID), \
                 patch.object(purec, "_ACTIVE_THREADS", 6), \
                 patch.object(purec, "prepare_voice_profile", side_effect=lambda *a, **k: next(profile_results)), \
                 patch.object(purec, "_stop_server_locked") as stop, \
                 patch.object(purec, "_start_server") as start:
                result = purec.compare_generated_voice_identity(
                    str(reference), str(generated), consent=True,
                    engine=purec.ENGINE_INT8_ID, thread_count=6)
            self.assertAlmostEqual(result["cosine_similarity"], 0.8, places=6)
            self.assertFalse(result["calibrated"])
            self.assertTrue(result["review_required"])
            stop.assert_called_once_with()
            start.assert_called_once()
            args, kwargs = start.call_args
            self.assertEqual(args[0], previous)
            self.assertEqual(kwargs["emotion_reference_path"], style)
            self.assertEqual(kwargs["emotion_reference_text"], "texto revisado")
            self.assertEqual(kwargs["engine"], purec.ENGINE_INT8_ID)
            self.assertEqual(kwargs["thread_count"], 6)


if __name__ == "__main__":
    unittest.main()
