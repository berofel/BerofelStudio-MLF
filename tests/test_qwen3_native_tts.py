"""Unit and optional hardware integration checks for the Qwen Turbo adapter."""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import wave
from unittest.mock import patch

import numpy as np

from berofel.services import qwen3_native_tts as native
from berofel.services.narration_service import NarrationRequest,generate_narration


class NativeQwenAdapterTests(unittest.TestCase):
    def test_native_layout_requires_all_three_runtime_assets(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{
                'BEROFEL_QWEN3_NATIVE_HOME':folder},clear=False):
            root=Path(folder);(root/'bin').mkdir();(root/'models').mkdir()
            for path in (root/'bin'/'qwen3-tts-cli.exe',
                         root/'models'/'qwen3-tts-0.6b-q4_0.gguf',
                         root/'models'/'qwen3-tts-tokenizer-f16-f32.gguf'):
                path.write_bytes(b'test')
            self.assertTrue(native.is_ready())
            (root/'models'/'qwen3-tts-tokenizer-f16-f32.gguf').unlink()
            self.assertFalse(native.is_ready())

    def test_wav_validation_accepts_audio_and_rejects_silence(self):
        with tempfile.TemporaryDirectory() as folder:
            audible=Path(folder)/'audible.wav'
            with wave.open(str(audible),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                output.writeframes(np.full(2400,1500,dtype='<i2').tobytes())
            duration,rate,frames=native._wav_info(audible)
            self.assertEqual((duration,rate,frames),(.1,24000,2400))
            silent=Path(folder)/'silent.wav'
            with wave.open(str(silent),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                output.writeframes(np.zeros(2400,dtype='<i2').tobytes())
            with self.assertRaisesRegex(ValueError,'silencioso'):
                native._wav_info(silent)

    def test_stream_reader_emits_complete_float_samples_and_drains_final_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'stream.f32';received=[];stats={}
            samples=np.array([-.5,.0,.5],dtype='<f4')
            third=samples[2:].tobytes()
            source.write_bytes(samples[:2].tobytes()+third[:2])
            offset=native._emit_stream_delta(source,0,received.append,stats,0.0)
            with source.open('ab') as output:output.write(third[2:])
            offset=native._emit_stream_delta(source,offset,received.append,stats,0.0)
            combined=b''.join(received)
            self.assertEqual(combined,samples.tobytes())
            self.assertEqual(offset,samples.nbytes)
            self.assertEqual(stats['bytes'],samples.nbytes)
            self.assertEqual(stats['chunks'],2)

    def test_native_encoder_prepares_and_reuses_its_own_versioned_embedding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);native_root=root/'native';(native_root/'bin').mkdir(parents=True)
            (native_root/'models').mkdir();exe=native_root/'bin'/'qwen3-tts-cli.exe'
            exe.write_bytes(b'exe');model=native_root/'models'/'qwen3-tts-0.6b-q4_0.gguf'
            model.write_bytes(b'q4 weights');tokenizer=native_root/'models'/'qwen3-tts-tokenizer-f16-f32.gguf'
            tokenizer.write_bytes(b'tokenizer');voice=root/'voice.wav';voice.write_bytes(b'authorized voice data')
            vector=np.linspace(-.5,.5,1024,dtype='<f4');calls=[]
            def prepare(_source,destination):
                Path(destination).write_bytes(b'normalized wav');return str(destination),None
            def extract(args,**kwargs):
                calls.append((args,kwargs));out=Path(args[args.index('--embedding-out')+1])
                out.write_bytes(struct.pack('<I',1024)+vector.tobytes())
                return type('ProcessResult',(),{'returncode':0,'stderr':'','stdout':''})()
            with patch.dict(os.environ,{'BEROFEL_QWEN3_NATIVE_HOME':str(native_root)}), \
                 patch('berofel.services.audio_reference.prepare_audio_prompt',side_effect=prepare), \
                 patch('berofel.services.qwen3_native_tts.subprocess.run',side_effect=extract):
                embedding,cache_hit,elapsed=native._native_embedding(voice,'authorized transcript',model)
                again,hit_again,elapsed_again=native._native_embedding(voice,'authorized transcript',model)
            self.assertFalse(cache_hit)
            self.assertTrue(hit_again)
            self.assertGreater(elapsed,0.0)
            self.assertEqual(elapsed_again,0.0)
            self.assertEqual(again,embedding)
            self.assertEqual(len(calls),1)
            with embedding.open('rb') as stream:
                self.assertEqual(struct.unpack('<I',stream.read(4))[0],1024)
                result=np.frombuffer(stream.read(),dtype='<f4')
            np.testing.assert_array_equal(result,vector)

    def test_narration_service_routes_native_engine_without_changing_default(self):
        with tempfile.TemporaryDirectory() as folder:
            voice=Path(folder)/'voice.wav';voice.write_bytes(b'authorized reference audio'*4)
            original=NarrationRequest(text='teste',voice=str(voice),consent=True)
            turbo=NarrationRequest(text='teste',voice=str(voice),consent=True,
                                   engine=native.ENGINE_ID)
            self.assertEqual(original.engine,'qwen3-tts-local')
            chunks=[]
            with patch.object(native,'generate_native_clone',return_value={'engine':native.ENGINE_ID}) as route:
                result=generate_narration(turbo,audio_chunk=chunks.append)
            self.assertEqual(result['engine'],native.ENGINE_ID)
            self.assertIs(route.call_args.kwargs['audio_chunk'].__self__,chunks)
            route.assert_called_once()


@unittest.skipUnless(os.environ.get('BEROFEL_RUN_QWEN_TURBO_INTEGRATION')=='1',
                     'Defina BEROFEL_RUN_QWEN_TURBO_INTEGRATION=1 para usar os pesos locais.')
class NativeQwenRealIntegrationTests(unittest.TestCase):
    def test_real_base_voice_generation_through_canonical_narration_service(self):
        from berofel.services.voice_profiles import VoiceProfileManager
        profiles=VoiceProfileManager().list_profiles()
        profile=next(item for item in profiles if item.get('authorized') and item.get('reference_text'))
        chunks=[]
        result=generate_narration(NarrationRequest(
            text='O Berofel Studio está testando a narração rápida do Qwen em português brasileiro. Código '+uuid.uuid4().hex[:8],
            voice=profile['sample_path'],reference_text=profile['reference_text'],
            language='portuguese',consent=True,engine=native.ENGINE_ID,
            project_path=os.environ.get('BEROFEL_QWEN_TURBO_TEST_PROJECT','')),
            audio_chunk=chunks.append)
        path=Path(result['path'])
        self.assertTrue(path.is_file())
        duration,rate,frames=native._wav_info(path)
        self.assertGreater(duration,1.0);self.assertEqual(rate,24000);self.assertGreater(frames,24000)
        self.assertEqual(result['engine'],native.ENGINE_ID)
        self.assertTrue(chunks,'O servidor nativo não entregou chunks durante a geração.')
        self.assertEqual(sum(len(chunk) for chunk in chunks),frames*4)
        self.assertIsNotNone(result['first_audio_chunk_seconds'])
        self.assertIsNotNone(result['first_audio_request_seconds'])
        self.assertGreaterEqual(result['first_audio_request_seconds'],
                                result['first_audio_chunk_seconds'])
        self.assertGreater(result['streamed_pcm_bytes'],0)
        self.assertGreater(result['streamed_chunk_count'],0)


if __name__=='__main__':
    unittest.main()
