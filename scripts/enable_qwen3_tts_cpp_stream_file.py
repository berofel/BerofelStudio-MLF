"""Patch a separate qwen3-tts.cpp checkout to expose decoded chunks to a raw PCM file.

The original main.cpp is backed up once. The normal JSON response and complete WAV
remain intact; streaming is opt-in per request via stream_file.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def patch_source(source: str) -> str:
    if 'json_get_str(line, "stream_file")' in source:
        return source
    include_marker = '#include <iostream>'
    if include_marker not in source:
        raise ValueError('main.cpp upstream inesperado: include iostream não encontrado.')
    source = source.replace(include_marker, include_marker + '\n#include <fstream>\n#include <cstdio>\n#include <algorithm>', 1)
    field_marker = '        std::string embedding_in  = json_get_str(line, "embedding_in");'
    field_patch = field_marker + '''
        std::string stream_file   = json_get_str(line, "stream_file");
        int chunk_frames          = json_get_int(line, "chunk_frames", 6);'''
    if field_marker not in source:
        raise ValueError('main.cpp upstream inesperado: campo embedding_in não encontrado.')
    source = source.replace(field_marker, field_patch, 1)
    synth_marker = '''        qwen3_tts::tts_result result;
        if (!embedding_in.empty()) {'''
    synth_patch = '''        qwen3_tts::tts_result result;
        if (!stream_file.empty()) {
            std::remove(stream_file.c_str());
            const int safe_chunk_frames = std::max(1, std::min(12, chunk_frames));
            tts.set_audio_chunk_callback([stream_file](const float * samples, int32_t n_samples,
                                                       int32_t sample_rate, int is_last) -> int {
                (void)sample_rate; (void)is_last;
                std::ofstream chunk(stream_file, std::ios::binary | std::ios::app);
                if (!chunk) return 1;
                chunk.write(reinterpret_cast<const char *>(samples),
                            static_cast<std::streamsize>(n_samples * sizeof(float)));
                chunk.flush();
                return chunk ? 0 : 1;
            }, safe_chunk_frames);
        }
        if (!embedding_in.empty()) {'''
    if synth_marker not in source:
        raise ValueError('main.cpp upstream inesperado: bloco de síntese não encontrado.')
    source = source.replace(synth_marker, synth_patch, 1)
    clear_marker = '''        if (!result.success) {
            fprintf(stderr, "[server] Request %d: synthesis failed: %s\\n",'''
    clear_patch = '''        if (!stream_file.empty()) tts.set_audio_chunk_callback(nullptr);
        if (!result.success) {
            fprintf(stderr, "[server] Request %d: synthesis failed: %s\\n",'''
    if clear_marker not in source:
        raise ValueError('main.cpp upstream inesperado: caminho de falha de síntese não encontrado.')
    source = source.replace(clear_marker, clear_patch, 1)
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True,
                        help='Checkout separado de CHE3MZ/qwen3-tts.cpp')
    args = parser.parse_args()
    source_path = (args.checkout / 'src' / 'main.cpp').resolve()
    if not source_path.is_file():
        parser.error(f'main.cpp não encontrado: {source_path}')
    backup = source_path.with_suffix('.cpp.qwen-turbo-original')
    if backup.exists():
        original = backup.read_text(encoding='utf-8')
    else:
        original = source_path.read_text(encoding='utf-8')
        backup.write_text(original, encoding='utf-8')
    source_path.write_text(patch_source(original), encoding='utf-8')
    print(f'Server com stream opcional instalado em {source_path}')
    print(f'Original preservado em {backup}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
