from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_qwen3_purec_stages.py"
SPEC = importlib.util.spec_from_file_location("benchmark_qwen3_purec_stages", SCRIPT)
BENCHMARK = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(BENCHMARK)


class PureCStageBenchmarkTests(unittest.TestCase):
    def test_parse_cli_stage_output(self):
        output = """Model loaded in 925 ms
Prefill: 386 ms
Talker step: 1143 ms (16.3 ms/f), Code Predictor: 2744 ms (39.2 ms/f)
Embed: 1 ms, Codec head+sampling: 17 ms
Speech decoder: 2630 ms total (254 ms drain after gen)
Audio: 5.6s generated in 4.6s (RTF 0.82)
TTFA: 1278 ms (first audio chunk, 10-frame chunk)
"""
        timing = BENCHMARK.parse_timings(output)
        self.assertEqual(timing["model_load_seconds"], .925)
        self.assertEqual(timing["prefill_seconds"], .386)
        self.assertEqual(timing["talker_seconds"], 1.143)
        self.assertEqual(timing["code_predictor_seconds"], 2.744)
        self.assertEqual(timing["decoder_seconds"], 2.63)
        self.assertEqual(timing["decoder_drain_seconds"], .254)
        self.assertEqual(timing["generation_seconds"], 4.6)
        self.assertEqual(timing["first_audio_seconds"], 1.278)
        self.assertEqual(timing["rtf"], .82)

    def test_unreported_stages_are_none(self):
        timing = BENCHMARK.parse_timings("Audio: 3.0s generated in 4.0s (RTF 1.33)")
        self.assertIsNone(timing["talker_seconds"])
        self.assertIsNone(timing["code_predictor_seconds"])
        self.assertEqual(timing["generation_seconds"], 4.0)


if __name__ == "__main__":
    unittest.main()
