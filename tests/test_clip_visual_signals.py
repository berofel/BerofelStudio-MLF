"""Tests for cached low-resolution visual-change proxies."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from berofel.core.project import Clip
from berofel.services.clip_visual_signals import (
    read_cached_visual_signals, score_cached_visual_interval)
from berofel.services.clipper import ClipperOptions, analyze_clips
from berofel.services.discourse_features import content_terms


class ThumbnailProvider:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.requests = []

    def get_thumb(self, source, at, request=True):
        self.requests.append((int(at), request))
        path = self.folder / f'{int(at)}.jpg'
        return str(path) if path.is_file() else ''


def _write_thumbnails(folder, seconds=36):
    folder = Path(folder)
    for at in range(seconds):
        pixels = np.zeros((80, 140), dtype=np.uint8)
        if at >= 10:
            # A repeatable coarse change, not semantic event content.
            pixels[:, :70] = 220 if at % 2 else 35
            pixels[:, 70:] = 35 if at % 2 else 220
        Image.fromarray(pixels, mode='L').save(folder / f'{at}.jpg', quality=95)


class ClipVisualSignalTests(unittest.TestCase):
    def test_reads_only_existing_thumbnails_and_scores_relative_change(self):
        with tempfile.TemporaryDirectory(prefix='bfs_visual_cache_') as folder:
            _write_thumbnails(folder, 20)
            provider = ThumbnailProvider(folder)
            signals = read_cached_visual_signals('unused.mov', 0., 20., provider)
            self.assertIsNotNone(signals)
            low = score_cached_visual_interval(signals, 1_000., 8_000.)
            high = score_cached_visual_interval(signals, 11_000., 19_000.)
        self.assertTrue(provider.requests)
        self.assertTrue(all(request is False for _, request in provider.requests))
        self.assertIsNotNone(low['score'])
        self.assertIsNotNone(high['score'])
        self.assertGreater(high['score'], low['score'])
        self.assertIn('não identifica conteúdo', high['reason'])

    def test_sparse_or_missing_cache_is_unavailable_not_zero_relevance(self):
        with tempfile.TemporaryDirectory(prefix='bfs_visual_sparse_') as folder:
            provider = ThumbnailProvider(folder)
            signals = read_cached_visual_signals('unused.mov', 0., 12., provider)
            score = score_cached_visual_interval(signals, 0., 12_000.)
        self.assertIsNone(score['score'])
        self.assertIn('insuficiente', score['reason'])
        self.assertTrue(all(request is False for _, request in provider.requests))

    def test_visual_features_are_persisted_and_reused_without_reopening_jpegs(self):
        with tempfile.TemporaryDirectory(prefix='bfs_visual_feature_cache_') as folder:
            folder = Path(folder)
            thumbs = folder / 'thumbs'
            thumbs.mkdir()
            _write_thumbnails(thumbs, 20)
            provider = ThumbnailProvider(thumbs)
            first = read_cached_visual_signals('unused.mov',0.,20.,provider,
                cache_dir=folder/'analysis-cache')
            with patch('PIL.Image.open',side_effect=AssertionError('cache miss')):
                second = read_cached_visual_signals('unused.mov',0.,20.,provider,
                    cache_dir=folder/'analysis-cache')
        self.assertTrue(second.cache_hit)
        np.testing.assert_array_equal(first.sample_times_ms,second.sample_times_ms)
        np.testing.assert_array_equal(first.frame_change,second.frame_change)
        self.assertTrue(all(request is False for _, request in provider.requests))

    def test_visual_thumbnail_scan_honors_cancellation(self):
        class Cancelled:
            def checkpoint(self):
                raise RuntimeError('cancelled')
        with tempfile.TemporaryDirectory(prefix='bfs_visual_cancel_') as folder:
            provider=ThumbnailProvider(folder)
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                read_cached_visual_signals('unused.mov',0.,10.,provider,
                    control=Cancelled())
        self.assertEqual(provider.requests,[])

    def test_clip_analysis_adds_visual_dimension_from_cache_without_decoding_video(self):
        with tempfile.TemporaryDirectory(prefix='bfs_visual_rank_') as folder:
            folder = Path(folder)
            source = folder / 'source.mov'
            source.write_bytes(b'placeholder; visual comes only from cached JPEGs')
            thumbs = folder / 'thumbs'
            thumbs.mkdir()
            _write_thumbnails(thumbs, 36)
            words = []
            at = 0.
            for index in range(150):
                token = ('O', 'editor', 'mantém', 'a', 'transcrição', 'salva',
                         'e', 'organiza', 'as', 'palavras')[index % 10]
                words.append({'id':f'w{index}','source':str(source.resolve()),
                    'source_start':at,'source_end':at+.14,'text':token})
                at += .2
            provider = ThumbnailProvider(thumbs)
            clip = Clip(str(source), 0., 30., kind='video')
            options = ClipperOptions(4., 12., 6, 6., 'Gameplay', 'Rápido', True)
            result = analyze_clips([clip], words, options,
                cache_dir=folder/'analysis-cache', visual_provider=provider)
            reranked = analyze_clips([clip], words,
                ClipperOptions(4.,12.,6,6.,'Podcast','Rápido',True),
                cache_dir=folder/'analysis-cache',visual_provider=provider)
        self.assertTrue(result['candidates'])
        self.assertTrue(any(c['visual_score'] is not None and
                            c['score_components']['visual'] is not None
                            for c in result['candidates']))
        self.assertEqual(result['stats']['visual_frames_reused'], 31)
        self.assertEqual(reranked['stats']['visual_cache_hits'],1)
        self.assertTrue(all(request is False for _, request in provider.requests))
        self.assertEqual(content_terms('O editor mantém a transcrição salva')['editor'], 1)


if __name__ == '__main__':
    unittest.main()
