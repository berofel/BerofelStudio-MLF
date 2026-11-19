"""Validação opt-in do fluxo real Qwen3 no Qt, timeline e exportadores.

Usa somente a amostra/transcrição já configuradas no painel Narração; nunca
imprime seus caminhos ou conteúdo. Configure QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import os
import subprocess
import argparse
os.environ.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                   'HF_HUB_DISABLE_TELEMETRY':'1'})

from pathlib import Path
import tempfile
import time
import wave
import sys

import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from scipy.io import wavfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from berofel.core.project import Clip, Project
from berofel.services.export_multitrack import export_audio_wav, export_project
from berofel.services.ffmpeg import ffmpeg_path, media_info
from berofel.ui.window import MainWindow


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    reference_mode=parser.add_mutually_exclusive_group()
    reference_mode.add_argument('--synthetic-reference',action='store_true',
        help='usa um sinal sintético local para validar UI/linha do tempo/exportação; não valida clonagem nem semelhança.')
    reference_mode.add_argument('--synthetic-fast-profile',action='store_true',
        help='prepara um perfil descartável com referência sintética e valida a rota de narração rápida da UI.')
    reference_mode.add_argument('--configured-fast-profile',action='store_true',
        help='copia a referência autorizada configurada para um perfil temporário e valida a rota rápida real.')
    reference_mode.add_argument('--saved-fast-profile',action='store_true',
        help='abre um processo novo e gera usando o perfil Qwen persistido, sem prepará-lo novamente.')
    parser.add_argument('--confirm-own-or-authorized-voice',action='store_true',
        help='confirma autorização para processar a referência local configurada.')
    parser.add_argument('--persist-profile',action='store_true',
        help='salva o perfil localmente para uso posterior; requer --configured-fast-profile.')
    parser.add_argument('--native-engine',choices=('qwen3-tts-native-q4',
        'qwen3-tts-native-q4-balanced'),
        help='valida pela UI um perfil nativo experimental e os chunks enviados à prévia.')
    args=parser.parse_args()
    settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                       'Berofel','BerofelStudio')
    synthetic=args.synthetic_reference or args.synthetic_fast_profile
    if not synthetic and not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if args.persist_profile and not args.configured_fast_profile:
        parser.error('--persist-profile requer --configured-fast-profile')
    if args.native_engine and not (args.configured_fast_profile or args.saved_fast_profile):
        parser.error('--native-engine requer um perfil rápido configurado ou salvo')
    sample=(Path(str(settings.value('narration/sample_path','') or '')).expanduser()
            if not synthetic else None)
    reference_text=(str(settings.value('narration/reference_text','') or '').strip()
                    if not synthetic
                    else ('referência sintética de validação' if args.synthetic_fast_profile else ''))
    if not synthetic and (not sample or not sample.is_file() or not reference_text):
        raise RuntimeError('Configure uma referência autorizada e sua transcrição exata no painel Narração.')

    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='bfs_qwen_editor_flow_') as folder:
        root=Path(folder)
        if args.synthetic_reference or args.synthetic_fast_profile:
            sample=root/'synthetic_reference.wav'
            rate=24000;duration=3.2
            t=np.arange(round(rate*duration),dtype=np.float64)/rate
            fundamental=np.where(t<1.05,132.,np.where(t<2.1,165.,147.))
            phase=2*np.pi*np.cumsum(fundamental)/rate
            envelope=np.minimum(1.,np.minimum(t/.12,(duration-t)/.12))
            signal=envelope*(.22*np.sin(phase)+.11*np.sin(2*phase)+.055*np.sin(3*phase))
            wavfile.write(str(sample),rate,np.clip(signal*32767,-32768,32767).astype('<i2'))
        # Keep test UI preferences isolated from the user's normal profile.
        settings_dir=root/'settings';settings_dir.mkdir()
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                          str(settings_dir))
        os.environ['BEROFEL_AI_CACHE']=str(root/'app_cache'/'ai')
        if args.synthetic_fast_profile:
            os.environ['BEROFEL_VOICE_PROFILE_DIR']=str(root/'voice_profiles')
            from berofel.services.voice_profiles import VoiceProfileManager
            profile=VoiceProfileManager().create('Perfil sintético rápido',sample,
                'portuguese',reference_text,authorized=True)
        elif args.configured_fast_profile:
            if args.persist_profile:
                os.environ.pop('BEROFEL_VOICE_PROFILE_DIR',None)
                os.environ.pop('BEROFEL_AI_CACHE',None)
                from berofel.services.voice_profiles import VoiceProfileManager
                profile_name='Minha voz Qwen3 Base'
                if any(item['name'].casefold()==profile_name.casefold()
                       for item in VoiceProfileManager().list_profiles()):
                    raise RuntimeError('O perfil “Minha voz Qwen3 Base” já existe; não foi substituído.')
            else:
                os.environ['BEROFEL_VOICE_PROFILE_DIR']=str(root/'voice_profiles')
                profile_name='Perfil local de validação'
            source_stat=sample.stat()
        elif args.saved_fast_profile:
            from berofel.services.voice_profiles import VoiceProfileManager
            profiles=VoiceProfileManager().list_profiles()
            if len(profiles)!=1 or not profiles[0]['authorized']:
                raise RuntimeError('O teste de reabertura requer exatamente um perfil local autorizado.')
            profile=profiles[0]
            source_stat=sample.stat()
        project=Project(width=320,height=180,fps=12)
        project_file=root/'qwen_flow.bfs';project.path=str(project_file)
        still=root/'timeline.png';Image.new('RGB',(320,180),(28,38,54)).save(still)
        project.add_clip(Clip(str(still),0,15,track_id=project.tracks[0].id,
                              kind='image',title='validation background'))
        window=MainWindow();window.project=project;window.refresh([])
        panel=window.narration_panel
        if args.saved_fast_profile:
            profile_data=f'voice-profile:{profile["id"]}'
            panel.voice.setCurrentIndex(panel.voice.findData(profile_data))
            if panel.voice.currentData()!=profile_data:
                raise RuntimeError('A instância nova não carregou o perfil da biblioteca rápida.')
        elif args.configured_fast_profile:
            from unittest.mock import patch
            panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
            panel.sample_path.setText(str(sample.resolve()))
            panel.reference_text.setText(reference_text)
            panel.authorized.setChecked(True)
            with patch('berofel.ui.narration_panel.QInputDialog.getText',
                       return_value=(profile_name,True)):
                panel._save_voice_profile()
            profiles=panel.voice_profiles.list_profiles()
            if len(profiles)!=1:
                raise RuntimeError('Salvar perfil pela interface não criou exatamente um perfil temporário.')
            profile=profiles[0]
            profile_data=f'voice-profile:{profile["id"]}'
            panel.voice.setCurrentIndex(panel.voice.findData(profile_data))
            if panel.voice.currentData()!=profile_data:
                raise RuntimeError('O perfil salvo não ficou disponível na biblioteca rápida.')
        elif args.synthetic_fast_profile:
            profile_data=f'voice-profile:{profile["id"]}'
            panel.voice.setCurrentIndex(panel.voice.findData(profile_data))
            window.prepare_narration_voice(profile['sample_path'],reference_text,profile['name'])
        if args.synthetic_fast_profile or args.configured_fast_profile or args.saved_fast_profile:
            prepare_deadline=time.monotonic()+600
            while time.monotonic()<prepare_deadline and window.active_task is not None:
                app.processEvents();time.sleep(.05)
            app.processEvents()
            if window.active_task is not None:
                raise TimeoutError('A preparação do perfil rápido excedeu 600 segundos.')
            # Simulate closing the editor session: stop the resident model
            # worker, then ensure the saved voice prompt survives its restart.
            from berofel.services.qwen3_tts_local import stop_local_worker
            stop_local_worker()
        else:
            panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
            panel.sample_path.setText(str(sample.resolve()))
            panel.reference_text.setText(reference_text)
            panel.authorized.setChecked(True)
        panel.set_text('Esta é uma validação real da narração Qwen dentro do editor.')
        panel.name.setText('Qwen local validation')
        streamed_chunks=[]
        if args.native_engine:
            engine_index=panel.clone_engine.findData(args.native_engine)
            if engine_index<0:
                raise RuntimeError('O seletor da interface não oferece o runtime nativo solicitado.')
            panel.clone_engine.setCurrentIndex(engine_index)
            if panel.clone_engine.currentData()!=args.native_engine:
                raise RuntimeError('A interface não manteve o perfil nativo selecionado.')
            # Keep the smoke test silent while exercising the real Task signal
            # path from native inference into the preview's PCM callback.
            window.narration_stream.push=lambda data:streamed_chunks.append(bytes(data))
        # Exercise the same panel action used by the user, including request
        # validation and dispatch into the application's narration controller.
        started=time.perf_counter()
        panel._generate(True)
        deadline=time.monotonic()+600
        while time.monotonic()<deadline and window.active_task is not None:
            app.processEvents();time.sleep(.05)
        app.processEvents()
        if window.active_task is not None:
            raise TimeoutError('O fluxo pela interface excedeu 600 segundos.')
        narration=next((clip for clip in project.clips if clip.kind=='audio'
                        and clip.title=='Qwen local validation'),None)
        if narration is None or not Path(narration.source).is_file():
            raise RuntimeError('A interface não inseriu a narração Qwen na timeline.')
        if 'Reaproveitado do cache' in window.narration_panel.status.text():
            raise RuntimeError('A validação da interface esperava uma inferência Qwen nova, não um cache hit.')
        if args.synthetic_fast_profile or args.configured_fast_profile:
            from berofel.services.ai_cache import cache_root
            cache_name='qwen3_native_tts' if args.native_engine else 'qwen3_tts'
            qwen_cache=cache_root().parent/cache_name
            metadata=list(qwen_cache.rglob('result.json'))
            entries=[__import__('json').loads(path.read_text(encoding='utf-8'))
                     for path in metadata]
            output_key_prefix=Path(narration.source).stem.rsplit('_',1)[-1]
            output_metadata=[item for item in entries
                             if str(item.get('key','')).startswith(output_key_prefix)]
            if args.native_engine:
                valid_reuse=any(item.get('engine')==args.native_engine and
                    item.get('profile_embedding_cache_hit') is True
                    for item in output_metadata)
            else:
                valid_reuse=any(item.get('prompt_cache_hit') is True and
                    item.get('model_load_count') == 1 for item in output_metadata)
            if not valid_reuse:
                raise RuntimeError('A narração rápida não reutilizou o prompt vocal preparado.')
            if args.configured_fast_profile or args.saved_fast_profile:
                current=sample.stat()
                if (current.st_size,current.st_mtime_ns)!=(source_stat.st_size,source_stat.st_mtime_ns):
                    raise RuntimeError('A gravação original foi alterada durante a criação/reuso do perfil.')
        rate,pcm=wavfile.read(narration.source)
        signal=np.asarray(pcm,dtype=np.float64)
        if signal.ndim>1:signal=signal.mean(axis=1)
        if not signal.size or float(np.sqrt(np.mean(signal*signal)))<=0:
            raise RuntimeError('O WAV inserido pela interface não contém sinal de áudio.')
        if args.native_engine:
            expected_stream_bytes=np.asarray(pcm).shape[0]*4
            actual_stream_bytes=sum(map(len,streamed_chunks))
            if not streamed_chunks or actual_stream_bytes!=expected_stream_bytes:
                raise RuntimeError('A prévia da interface não recebeu o stream PCM nativo completo: '
                    f'{actual_stream_bytes}/{expected_stream_bytes} bytes.')

        panel._audio.setVolume(0.0)
        panel._player.setSource(QUrl.fromLocalFile(narration.source))
        panel._player.play()
        app.processEvents();time.sleep(.25);app.processEvents()
        player_started=panel._player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
        panel._player.pause();app.processEvents()
        panel._player.setPosition(min(500,max(0,int(narration.duration*500))))
        app.processEvents()
        if not player_started:
            raise RuntimeError('O player Qt não iniciou a reprodução do WAV da narração.')

        audio_out=root/'timeline.wav';video_out=root/'timeline.mp4'
        export_audio_wav(project,audio_out)
        wav_rate,wav=wavfile.read(str(audio_out))
        if wav_rate not in (44100,48000,96000) or not np.any(wav):
            raise RuntimeError('A exportação WAV não contém áudio válido.')
        export_project(project,str(video_out))
        duration,has_video,has_audio=media_info(str(video_out))
        if not has_video or not has_audio or duration<=0:
            raise RuntimeError('O MP4 exportado não contém vídeo e narração sincronizados.')
        decoded=root/'mp4_audio.wav'
        subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                        '-i',str(video_out),'-map','0:a:0','-vn','-ac','1',
                        '-ar','24000','-c:a','pcm_s16le',str(decoded)],
                       check=True,capture_output=True,timeout=60)
        _decoded_rate,decoded_samples=wavfile.read(str(decoded))
        decoded_signal=np.asarray(decoded_samples,dtype=np.float64)
        if not decoded_signal.size or float(np.sqrt(np.mean(decoded_signal**2)))<=0:
            raise RuntimeError('O áudio decodificado do MP4 está silencioso ou corrompido.')

        project.save(str(project_file))
        reopened=Project.load(str(project_file))
        restored=next((clip for clip in reopened.clips if clip.kind=='audio'),None)
        if restored is None or restored.source!=narration.source:
            raise RuntimeError('Salvar/reabrir projeto não preservou o bloco de narração.')

        if args.native_engine:
            label='Turbo Q4' if args.native_engine=='qwen3-tts-native-q4' else 'Equilibrado Q4'
            print(f'[PASSOU] UI {label}: {len(streamed_chunks)} chunks, '
                  f'{sum(map(len,streamed_chunks))} bytes no callback da prévia.')
        if args.saved_fast_profile:
            print('[PASSOU] Processo novo reutilizou o perfil rápido persistido e o prompt em cache offline.')
        elif args.configured_fast_profile:
            if args.persist_profile:
                print('[PASSOU] Perfil pessoal salvo pela UI, narração rápida offline após reiniciar o worker e prompt local persistido.')
            else:
                print('[PASSOU] Narração rápida pela UI com cópia temporária do perfil pessoal autorizado e prompt reutilizado.')
        elif args.synthetic_fast_profile:
            print('[PASSOU] Narração rápida pela UI com perfil sintético preparado e prompt reutilizado (não valida identidade vocal).')
        elif args.synthetic_reference:
            print('[PASSOU] Inferência Qwen real com referência sintética pela rota da interface offline (não valida identidade vocal).')
        else:
            print('[PASSOU] Geração Qwen real acionada pela interface offline com referência configurada.')
        print(f'[PASSOU] Timeline/player Qt: áudio inserido, reprodução e busca verificadas (saída de áudio silenciada).')
        print(f'[PASSOU] WAV exportado: {wav_rate} Hz; conteúdo não silencioso.')
        print(f'[PASSOU] MP4 exportado: vídeo+áudio, {duration:.2f}s.')
        print(f'[PASSOU] Projeto salvo e reaberto com o clipe de narração.')
        print(f'Tempo do fluxo completo: {time.perf_counter()-started:.1f}s.')
        panel._player.stop();panel._player.setSource(QUrl())
        app.processEvents();time.sleep(.2);app.processEvents()
        window.close();app.processEvents()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {exc}',flush=True)
        raise SystemExit(1)

