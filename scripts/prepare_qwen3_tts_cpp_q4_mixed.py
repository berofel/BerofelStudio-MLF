"""Create a separate experimental Q4_0 converter beside a qwen3-tts.cpp clone.

The upstream converter remains untouched. This experimental profile quantizes
supported matrix weights to Q4_0, keeps the speaker encoder and sensitive
embeddings/norms/heads at F16, and logs any unsupported shapes that fall back.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def patch_text(source: str) -> str:
    if 'choices=["f16", "f32", "q8_0", "q4_0"]' in source:
        raise ValueError('O conversor já contém a opção q4_0; não será alterado.')

    speaker_marker='''        # Keep embeddings in F16
        if any(x in tensor_name for x in ["_embd", "codebook"]):'''
    speaker_patch='''        # Keep speaker encoder weights in F16: native Q4 vectors showed a
        # measurable intelligibility regression in local tests.
        if tensor_name.startswith("speaker_encoder."):
            return False

        # Keep embeddings in F16
        if any(x in tensor_name for x in ["_embd", "codebook"]):'''
    if speaker_marker not in source:
        raise ValueError('Conversor upstream inesperado: política de embeddings não encontrada.')
    source=source.replace(speaker_marker,speaker_patch,1)

    q8_branch='''        elif self.output_type == "q8_0":
            if not self._should_quantize(tensor_name):'''
    q4_branch='''        elif self.output_type == "q4_0":
            if not self._should_quantize(tensor_name):
                return data.astype(np.float16), gguf.GGMLQuantizationType.F16
            data = data.astype(np.float32)
            try:
                quantized = gguf.quants.quantize(data, gguf.GGMLQuantizationType.Q4_0)
                return quantized, gguf.GGMLQuantizationType.Q4_0
            except Exception as e:
                logger.warning(f"Q4_0 quantization failed for {tensor_name}: {e}, falling back to F16")
                return data.astype(np.float16), gguf.GGMLQuantizationType.F16
        elif self.output_type == "q8_0":
            if not self._should_quantize(tensor_name):'''
    if q8_branch not in source:
        raise ValueError('Conversor upstream inesperado: ramo Q8 não encontrado.')
    source=source.replace(q8_branch,q4_branch,1)

    ftype_marker='''        elif self.output_type == "q8_0":
            ftype = gguf.LlamaFileType.MOSTLY_Q8_0'''
    ftype_patch='''        elif self.output_type == "q4_0":
            ftype = gguf.LlamaFileType.MOSTLY_Q4_0
        elif self.output_type == "q8_0":
            ftype = gguf.LlamaFileType.MOSTLY_Q8_0'''
    if ftype_marker not in source:
        raise ValueError('Conversor upstream inesperado: tabela de file types não encontrada.')
    source=source.replace(ftype_marker,ftype_patch,1)

    choices='choices=["f16", "f32", "q8_0"]'
    if choices not in source:
        raise ValueError('Conversor upstream inesperado: lista de precisões não encontrada.')
    source=source.replace(choices,'choices=["f16", "f32", "q8_0", "q4_0"]',1)
    return source


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-root',type=Path,required=True,
                        help='Checkout separado de CHE3MZ/qwen3-tts.cpp.')
    parser.add_argument('--output',type=Path,
                        help='Saída; por padrão cria scripts/convert_tts_to_gguf_q4_mixed_exp.py no checkout.')
    args=parser.parse_args()
    original=(args.upstream_root/'scripts'/'convert_tts_to_gguf.py').resolve()
    if not original.is_file():parser.error(f'Conversor upstream não encontrado: {original}')
    destination=(args.output.resolve() if args.output else
        original.with_name('convert_tts_to_gguf_q4_mixed_exp.py'))
    if destination==original:parser.error('A saída não pode sobrescrever o conversor original.')
    patched=patch_text(original.read_text(encoding='utf-8'))
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(patched,encoding='utf-8')
    print(f'Conversor experimental separado criado: {destination}')
    print('O arquivo upstream não foi modificado; inspecione os avisos de fallback do Q4_0.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
