import sys
import unittest
from unittest.mock import patch

from scripts.benchmark_qwen3_turbo_backends import parse_args


class QwenTurboBenchmarkArgsTests(unittest.TestCase):
    def test_accepts_supported_thread_counts(self):
        for threads in (2, 4, 6, 8):
            with self.subTest(threads=threads), patch.object(
                    sys, "argv", ["benchmark", "--confirm-own-or-authorized-voice",
                                  "--output-dir", "C:/benchmark", "--threads", str(threads)]):
                self.assertEqual(parse_args().threads, threads)

    def test_defaults_to_six_threads(self):
        with patch.object(sys, "argv", ["benchmark", "--confirm-own-or-authorized-voice",
                                         "--output-dir", "C:/benchmark"]):
            self.assertEqual(parse_args().threads, 6)

    def test_rejects_unsupported_thread_count(self):
        with patch.object(sys, "argv", ["benchmark", "--confirm-own-or-authorized-voice",
                                         "--output-dir", "C:/benchmark", "--threads", "3"]):
            with self.assertRaises(SystemExit):
                parse_args()


if __name__ == "__main__":
    unittest.main()
