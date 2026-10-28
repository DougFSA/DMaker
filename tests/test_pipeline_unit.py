"""Pipeline completo com dependências falsas: sem ffmpeg, sem Whisper. Verifica a orquestração,
o cache, o ASS gerado e o tratamento de silêncio."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from dmaker.domain.spec import AudioTrack, Project, SourceRef, TrackState
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.text.captions import Cue, Word
from dmaker.text.transcribe import Transcript

LOUDNORM_JSON = json.dumps(
    {
        "input_i": "-23.5",
        "input_tp": "-4.0",
        "input_lra": "7.0",
        "input_thresh": "-33.9",
        "target_offset": "0.3",
    }
)
SILENT_JSON = json.dumps(
    {
        "input_i": "-inf",
        "input_tp": "-inf",
        "input_lra": "0.0",
        "input_thresh": "-inf",
        "target_offset": "0.0",
    }
)


class FakeTranscriber:
    calls = 0

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        FakeTranscriber.calls += 1
        assert wav.name == "voice.wav"
        assert initial_prompt and "MedlyCare" in initial_prompt  # vocabulário do tema chega ao modelo
        return Transcript(
            [
                Cue(
                    0.2,
                    1.4,
                    "chega de medriquer",
                    [Word(0.2, 0.6, "chega"), Word(0.6, 0.9, "de"), Word(0.9, 1.4, "medriquer")],
                )
            ],
            {"language": language},
        )


def fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".png":
        return MediaInfo(path, 0.0, 1000, 620, 0.0, True, False, True)
    return MediaInfo(path, 8.0, 1920, 1080, 30.0, True, True, False)


def touch_output(command: FFmpegCommand) -> None:
    """Simula o ffmpeg criando o arquivo de saída (último argumento)."""
    out = Path(command.args[-1])
    if command.label == "acabamento da fala":  # o acabamento devolve a própria fala (um WAV que se pode ler)
        shutil.copyfile(command.args[command.args.index("-i") + 1], out)
        return
    if out.suffix in (".mov", ".mp4", ".wav", ".jpg"):
        if command.cwd and not out.is_absolute():
            out = command.cwd / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 1024)


@pytest.fixture
def workspace(tmp_path: Path) -> dict:
    from PIL import Image

    (tmp_path / "take.mp4").write_bytes(b"x")  # o probe é falso; só precisa existir
    Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    spec = {
        "name": "unit",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",
        "timeline": [
            {"type": "card", "title": "Abertura", "duration": 1.0, "motion": "none"},
            {
                "type": "clip",
                "src": "take.mp4",
                "start": 1,
                "end": 3,
                "transition": {"type": "fade", "duration": 0.4},
            },
            {
                "type": "image",
                "src": "print.png",
                "duration": 1.0,
                "motion": "zoom-in",
                "transition": {"type": "cut"},
            },
        ],
        "overlays": [
            {"type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.1},
            {"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 0.9},
            {"type": "progress-bar"},
        ],
        "captions": {"source": "auto", "language": "pt"},
        "audio": {"normalize": "two-pass"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return {"project": project, "dir": tmp_path}


def _pipeline(workspace: dict, runner: RecordingRunner, **opts) -> RenderPipeline:
    d = workspace["dir"]
    return RenderPipeline(
        workspace["project"],
        RenderOptions(preview=True, quiet=True, out=d / "out.mp4", **opts),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        cache_dir=d / "mez",
        jobs_dir=d / "jobs",
        output_dir=d / "output",
    )


def test_full_pipeline_with_fakes(workspace):
    FakeTranscriber.calls = 0
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(workspace, runner).run()

    labels = [c for c in runner.commands]
    # 3 mezaninos + áudio para transcrição + medição de loudness + montagem + thumbnail
    assert len(labels) == 7
    assert runner.frames_consumed == 30  # 1 s a 30 fps do trecho com movimento (gerado de verdade)
    assert result.output.exists() and result.duration == pytest.approx(1.0 + 2.0 - 0.4 + 1.0)
    assert FakeTranscriber.calls == 1

    final = runner.commands[-2]
    assert "-/filter_complex" in final or "-filter_complex_script" in final
    assert "libx264" in final and "ultrafast" in final  # preview usa rascunho
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "xfade=transition=fade" in graph and "measured_I=-23.5" in graph and "overlay.ass" in graph

    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "Gancho" in ass and "MEDLYCARE" in ass  # legenda corrigida pelo tema (medriquer -> MedlyCare)
    assert "&H005A530C" in ass  # gancho sobre cartão claro sai na cor principal da marca
    store = workspace["dir"] / "captions.auto.json"
    assert store.exists() and json.loads(store.read_text(encoding="utf-8"))["hash"]


def test_rounded_captions_and_text_boxes_reach_the_ass(workspace):
    """O modo `rounded` e a opção `box_shape` da spec chegam ao ASS da montagem, com a caixa sob o texto."""
    project = workspace["project"]
    project.captions.style.mode = "rounded"
    project.overlays[1].style.box_shape = "rounded"
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(workspace, runner).run()

    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    caption_boxes = [e for e in events if e.startswith("Dialogue: 4,") and "\\p1" in e]
    caption_texts = [e for e in events if e.startswith("Dialogue: 5,")]
    assert len(caption_boxes) == 1 and "\\q2" in caption_texts[0]  # uma caixa para a cue, texto sobre ela
    # o destaque anda palavra a palavra por cima da mesma caixa (a marca pinta a ativa de verde)
    assert len(caption_texts) == 3 and "&H00A2B975}MEDLYCARE" in caption_texts[2]
    hook_box = [e for e in events if e.startswith("Dialogue: 10,") and "\\p1" in e]
    assert len(hook_box) == 1 and " b " in hook_box[0]  # o gancho ganhou a caixa arredondada


def test_second_run_reuses_cache(workspace):
    FakeTranscriber.calls = 0
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _pipeline(workspace, runner).run()
    again = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _pipeline(workspace, again).run()
    # só medição de loudness, montagem e thumbnail: mezaninos e transcrição vieram do cache
    assert len(again.commands) == 3 and again.frames_consumed == 0
    assert FakeTranscriber.calls == 1
    forced = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _pipeline(workspace, forced, force=True).run()
    assert len(forced.commands) == 7 and FakeTranscriber.calls == 2


def test_silent_audio_skips_loudnorm(workspace):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=SILENT_JSON)
    result = _pipeline(workspace, runner, no_captions=True).run()
    assert any("silencioso" in w for w in result.warnings)
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "loudnorm" not in graph


def test_dry_run_records_without_files(workspace):
    result = _pipeline(workspace, RecordingRunner(), dry_run=True).run()
    assert not result.output.exists() and result.size_bytes == 0
    assert len(result.commands) >= 4 and result.thumbnail is None


def test_missing_source_fails_clearly(workspace):
    project = Project.model_validate({"name": "x", "timeline": [{"type": "clip", "src": "nao_existe.mp4"}]})
    project.base_dir = workspace["dir"]
    with pytest.raises(FileNotFoundError):
        RenderPipeline(
            project, RenderOptions(dry_run=True), runner=RecordingRunner(), prober=fake_prober
        ).run()


def test_render_respects_muted_and_hidden_tracks(workspace):
    """`apply_track_state` roda antes de resolver as fontes (pipeline/renderer.py): uma faixa de
    áudio externa muda não pode entrar na mixagem, e uma sobreposição de texto oculta não pode
    gerar evento nenhum no ASS. Prova ponta a ponta com RecordingRunner (sem ffmpeg de verdade)."""
    d = workspace["dir"]
    (d / "rec.wav").write_bytes(b"x")
    project = workspace["project"].model_copy(
        update={
            "sources": {"rec": SourceRef(src="rec.wav")},
            "audio": workspace["project"].audio.model_copy(update={"tracks": [AudioTrack(source="rec")]}),
            "tracks": {"A2": TrackState(muted=True), "TX": TrackState(hidden=True)},
        }
    )
    project.base_dir = d
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    pipeline = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=d / "out.mp4"),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        cache_dir=d / "mez",
        jobs_dir=d / "jobs",
        output_dir=d / "output",
    )
    result = pipeline.run()

    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "rec.wav" not in graph  # A2 muda: a faixa externa nunca entra na mixagem

    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "Gancho" not in ass  # TX oculta: a sobreposição de texto não gera evento nenhum


def _project_with_pending_multicam(base_dir: Path) -> Project:
    for name in ("cam1.mp4", "cam2.mp4"):
        target = base_dir / name
        if not target.exists():
            target.write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "pendente",
            "sources": {"cam1": {"src": "cam1.mp4"}, "cam2": {"src": "cam2.mp4"}},
            "timeline": [{"type": "clip", "source": "cam1", "start": 0, "end": 5}],
            "multicam": {"at": 1, "cameras": ["cam1", "cam2"], "main": "cam1", "audio": "cam1"},
        }
    )
    project.base_dir = base_dir
    return project


def test_summarize_warns_about_pending_multicam_block_without_failing(workspace):
    from dmaker.pipeline.projects import summarize

    project = _project_with_pending_multicam(workspace["dir"])
    summary = summarize(project, prober=fake_prober)

    assert any("bloco multicam" in w and "plan_multicam" in w for w in summary.warnings)


def test_render_pipeline_refuses_project_with_pending_multicam_block(workspace):
    project = _project_with_pending_multicam(workspace["dir"])
    with pytest.raises(ValueError, match="bloco multicam.*plan_multicam"):
        RenderPipeline(
            project, RenderOptions(dry_run=True), runner=RecordingRunner(), prober=fake_prober
        ).run()


def test_music_tail_span_uses_probed_duration_for_start_at(tmp_path):
    """`MusicSpan` com `tail` precisa da duração da música: `assembly.py` busca com `ctx.prober` (aqui,
    o falso, que devolve 8.0 s para qualquer arquivo que não seja `.png`)."""
    (tmp_path / "take.mp4").write_bytes(b"x")
    (tmp_path / "trilha.m4a").write_bytes(b"x")
    spec = {
        "name": "musica-no-fim",
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "audio": {
            "music": {
                "src": "trilha.m4a",
                "volume": 0.5,
                "loop": False,
                "ducking": False,
                "spans": [{"start": 2, "from_end": True, "tail": True, "start_at": 0.5}],
            },
            "normalize": "off",
        },
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    runner = RecordingRunner(on_run=touch_output)
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=fake_prober,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    # total = 4.0 (o clipe inteiro); from_end: start = 4 - 2 = 2.0; tail: comprimento = 4 - 2 = 2.0;
    # start_at efetivo = duração da música (8.0, do prober falso) - 2.0 - 0.5 (folga) = 5.5
    assert "atrim=start=5.500:duration=2.000" in graph
    assert "adelay=2000:all=1" in graph


# ---------- narração por texto ----------


class FakeSynthesizer:
    """Seno de 0,05 s por caractere, contando as sínteses (a real leva minutos na CPU)."""

    engine_id = "fake-pipeline"

    def __init__(self):
        self.texts: list[str] = []

    def synthesize(self, request):
        import numpy as np

        from dmaker.voice.synth import Speech

        self.texts.append(request.text)
        t = np.arange(int(len(request.text) * 0.05 * 24000)) / 24000
        return Speech((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 24000)


def _narrated_pipeline(directory: Path, synthesizer: FakeSynthesizer, runner: RecordingRunner, **audio):
    from dmaker.pipeline.narration import NarrationService
    from dmaker.voice.library import VoiceLibrary

    (directory / "trilha.mp3").write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "narrado",
            "timeline": [{"type": "card", "title": "Abertura", "duration": 6.0, "motion": "none"}],
            "captions": {"source": "narration"},
            "audio": {
                "narration": [{"text": "Olá, este é o DMaker.", "start": 0.5}],
                "music": {"src": "trilha.mp3"},
                **audio,
            },
        }
    )
    project.base_dir = directory
    return RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=directory / "out.mp4"),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: pytest.fail("legenda de narração não usa o Whisper"),
        cache_dir=directory / "mez",
        jobs_dir=directory / "jobs",
        output_dir=directory / "output",
        narrator=NarrationService(synthesizer, runner, directory / "voice-cache"),
        voice_library=VoiceLibrary(directory / "voices"),
    )


def test_render_mixes_narration_before_ducking_and_captions_it(tmp_path):
    synthesizer = FakeSynthesizer()
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _narrated_pipeline(tmp_path, synthesizer, runner).run()

    assert synthesizer.texts == ["Olá, este é o DMaker."]
    narration_wav = result.job_dir / "narration_1.wav"
    final, measurement = runner.commands[-2], next(c for c in runner.commands if "-f" in c and "null" in c)
    assert str(narration_wav) in final  # entra como entrada do comando final
    assert str(narration_wav) in measurement  # e do da medição, para o loudness final contá-la

    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "adelay=500:all=1[nar0]" in graph
    assert (
        graph.index("amix=inputs=2:duration=first")
        < graph.index("sidechaincompress")
        < graph.index("loudnorm")
    )
    assert "[a_narrated]asplit=2[voice][sc]" in graph

    assert result.captions_file == result.job_dir / "captions.narration.srt"
    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "OLÁ," in ass.upper() and "DMAKER" in ass.upper()  # legendas saem em caixa alta
    assert result.warnings == []


def test_render_reuses_the_cached_narration(tmp_path):
    synthesizer = FakeSynthesizer()
    first = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _narrated_pipeline(tmp_path, synthesizer, first).run()
    second = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    _narrated_pipeline(tmp_path, synthesizer, second).run()
    assert len(synthesizer.texts) == 1  # a fala veio do cache no segundo render


def test_narration_replaces_the_voice_of_a_video_without_speech(tmp_path):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _narrated_pipeline(tmp_path, FakeSynthesizer(), runner, mute_clips=True).run()
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "volume=0[a_mute]" in graph and "[a_mute][nar0]amix=inputs=2" in graph
    assert "sidechaincompress" in graph  # a música abaixa sob a narração mesmo com os clipes mudos


def test_render_warns_when_the_real_narration_passes_the_end(tmp_path):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    pipeline = _narrated_pipeline(tmp_path, FakeSynthesizer(), runner)
    pipeline.project.audio.narration[0] = pipeline.project.audio.narration[0].model_copy(
        update={"start": 5.5}
    )
    result = pipeline.run()
    assert any("audio.narration[0]" in w and "cortado" in w for w in result.warnings)


def test_dry_run_does_not_synthesize(tmp_path):
    synthesizer = FakeSynthesizer()
    pipeline = _narrated_pipeline(tmp_path, synthesizer, RecordingRunner())
    pipeline.options.dry_run = True
    result = pipeline.run()
    assert synthesizer.texts == [] and result.captions_file is None


# ---------- regiões nomeadas, quadro do rosto e áudio das sobreposições ----------

EXPLAINER_REGIONS = {
    "topo": {"x": 0.5, "y": 0.2575, "width": 0.7222, "height": 0.265},
    "rosto": {"x": 0.5, "y": 0.6, "width": 0.8889, "height": 0.36},
}


def _explainer(workspace: dict, **overrides) -> dict:
    """Projeto no formato do modelo "explicativo": dois fundos lisos, a gravação num quadro (região rosto)
    e a imagem (região topo) de cada assunto. Troca o projeto da oficina e devolve a própria oficina."""
    spec = {
        "name": "explicativo",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",  # o vocabulário da marca é o que o transcritor falso confere
        "regions": EXPLAINER_REGIONS,
        "timeline": [
            {
                "type": "card",
                "flat": True,
                "background": "#0F172A",
                "variant": "dark",
                "logo": False,
                "motion": "none",
                "duration": 4,
            },
            {
                "type": "card",
                "flat": True,
                "background": "#F1E8D8",
                "variant": "light",
                "logo": False,
                "motion": "none",
                "duration": 4,
            },
        ],
        "overlays": [
            {
                "type": "video",
                "src": "take.mp4",
                "region": "rosto",
                "shape": "rounded",
                "animation": "none",
                "focus": [0.5, 0.3],
            },
            {"type": "image", "src": "print.png", "region": "topo", "start": 0, "end": 4},
            {"type": "text", "text": "Assunto dois", "region": "topo", "start": 4, "end": 8},
        ],
        "captions": {"source": "auto", "language": "pt", "style": {"mode": "rounded", "y": 0.72}},
        "audio": {"normalize": "two-pass"},
        **overrides,
    }
    project = Project.model_validate(spec)
    project.base_dir = workspace["dir"]
    workspace["project"] = project
    return workspace


def test_regions_become_concrete_positions_in_the_final_graph(workspace):
    from dmaker.domain.regions import region_pixels
    from dmaker.domain.spec import Region

    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(_explainer(workspace), runner, no_captions=True).run()
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    left, top, width, height = region_pixels(Region(**EXPLAINER_REGIONS["rosto"]), 540, 960)

    # o quadro do rosto: o vídeo preenche a região (corta o excesso, sem distorcer) em torno do foco
    assert f"scale={width // 2 * 2}:{height // 2 * 2}:force_original_aspect_ratio=increase" in graph
    assert "crop=" in graph and ":(iw-ow)*0.5000:(ih-oh)*0.3000" in graph
    assert f"overlay=x='{left}':y='{top}'" in graph  # canto do quadro, pela região
    # a imagem do assunto (1000x620, mais larga que a região de cima) encosta nos lados e se centra nela
    image_width = int(re.search(r"\[2:v\]format=rgba,scale=(\d+):-2", graph).group(1))
    assert 386 <= image_width <= 390  # a largura da região (389.99 px), com o truncamento para par
    assert "overlay=x=270.00-w/2:y=247.20-h/2" in graph
    # o texto na região de cima já nasce no lugar dela (centro x 270, y 247)
    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "\\pos(270,247)" in ass


def test_the_face_frame_has_the_exact_pixels_of_the_region(workspace):
    """Regressão da conta em ponto flutuante: 480 / (480/226) dava 225.99999 e o quadro saía 2 px mais baixo."""
    regions = {"rosto": {"x": 0.5, "y": 0.6, "width": 480 / 540, "height": 226 / 960}}
    workspace = _explainer(
        workspace, regions=regions, overlays=[{"type": "video", "src": "take.mp4", "region": "rosto"}]
    )
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(workspace, runner, no_captions=True).run()
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "scale=480:226:force_original_aspect_ratio=increase" in graph


def test_the_loudness_pass_measures_the_audio_of_a_video_overlay(workspace):
    """No modelo "explicativo" a única voz é a da gravação, que é uma sobreposição: sem ela na medição o
    áudio saía medido como silêncio e a normalização era pulada."""
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(_explainer(workspace), runner, no_captions=True).run()
    measure = next(c for c in runner.commands if "null" in c and "-filter_complex" in c)
    chain = measure[measure.index("-filter_complex") + 1]
    assert "[pipaud0]" in chain and "amix=inputs=2" in chain and "loudnorm" in chain
    assert any(
        arg == str(workspace["dir"] / "take.mp4") for arg in measure
    )  # a gravação é uma entrada da medição
    assert not any("silencioso" in w for w in result.warnings)
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "measured_I=-23.5" in graph  # e a medida chega à normalização linear da montagem


def test_a_video_overlay_shorter_than_asked_is_reported(workspace):
    longer = [{"type": "card", "flat": True, "logo": False, "motion": "none", "duration": 12}]
    workspace = _explainer(workspace, timeline=longer)  # a gravação (falsa) tem 8 s, o vídeo pede 12
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(workspace, runner, no_captions=True).run()
    assert any("tem 8.0s" in w and "12.0s" in w and "some antes do fim" in w for w in result.warnings)
    quiet = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    assert not any(
        "some antes" in w for w in _pipeline(_explainer(workspace), quiet, no_captions=True).run().warnings
    )


def test_a_caption_can_ignore_the_tone_of_the_background(workspace):
    """Sobre o quadro do rosto a legenda fica sobre vídeo: o tom do fundo ao redor não troca o estilo dela."""

    def caption_styles(follow: bool) -> str:
        project = _explainer(workspace)["project"]
        project.captions.style.follow_background = follow
        runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
        result = _pipeline(workspace, runner, force=True).run()
        return (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")

    following = caption_styles(True)
    assert "Style: CapDark," in following  # a cue cai sobre o fundo escuro do primeiro assunto
    ignoring = caption_styles(False)
    assert "Style: Cap," in ignoring and "CapDark" not in ignoring
