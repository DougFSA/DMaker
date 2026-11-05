"""Estado de trilha (mudo, solo, ganho, pan, oculto, bloqueado) da vista multitrilha, aplicado à spec.

`apply_track_state` existe porque, como no Shotcut e no Audacity, mudar ou ocultar uma trilha no editor precisa
valer tanto para a prévia ao vivo quanto para o RENDER final: sem isso, o usuário silenciaria uma
faixa na interface e ela continuaria audível no vídeo exportado. `locked` é só da interface (trava
seleção/arraste dos itens da trilha) e não muda nada aqui."""

from __future__ import annotations

from .markers import marker_groups, marker_track_id
from .spec import ClipSegment, HtmlOverlay, ImageOverlay, ProgressBar, Project, TextOverlay, VideoOverlay
from .timeline import stack_lanes

# Uma trilha de efeitos sonoros "muda" vira este ganho: a spec não tem como dizer -infinito, e 120 dB abaixo está
# bem abaixo do que qualquer saída de 16 ou 24 bits consegue guardar
SILENT_GAIN_DB = -120.0


def video_overlay_lanes(project: Project) -> dict[int, int]:
    """Faixa (0 = V2, 1 = V3...) de cada sobreposição de vídeo (picture-in-picture) de
    `project.overlays`, pela mesma regra de empilhamento da vista multitrilha
    (`pipeline.timeline_view.stack_lanes`): duas que não se cruzam no tempo dividem a mesma faixa.
    Chave do dicionário devolvido = índice em `project.overlays`."""
    video_indices = [i for i, ov in enumerate(project.overlays) if isinstance(ov, VideoOverlay)]
    intervals = []
    for i in video_indices:
        ov = project.overlays[i]
        end = ov.end if ov.end is not None else float("inf")
        intervals.append((ov.start, end))
    lane_of = stack_lanes(intervals)
    return dict(zip(video_indices, lane_of, strict=True))


def known_track_ids(project: Project) -> set[str]:
    """ids de trilha que fazem sentido para esta spec (as mesmas que `build_timeline_view`
    mostraria): usado pelo lint para avisar de um id desconhecido em `project.tracks`. A `SFX` não aparece na vista,
    mas guarda o ganho, o pan e o mudo do barramento dos efeitos sonoros."""
    ids = {"V1", "A1", "TX", "GR", "CC", "MUS", "SFX"}
    ids.update(f"A{2 + i}" for i in range(len(project.audio.tracks)))
    if project.audio.narration:
        ids.add("NAR")
    if project.audio.voiceover:
        ids.add("VO")
    lanes = video_overlay_lanes(project)
    ids.update(f"V{2 + lane}" for lane in set(lanes.values()))
    ids.update(marker_track_id(group) for group in marker_groups(project.markers))
    return ids


def audio_track_ids(project: Project) -> list[str]:
    """As trilhas de áudio do projeto, na ordem da vista: o som dos clipes (A1), as faixas externas (A2...),
    narração, voz gravada, música e o barramento dos efeitos sonoros. É o conjunto em que o solo vale."""
    ids = ["A1", *(f"A{2 + i}" for i in range(len(project.audio.tracks)))]
    if project.audio.narration:
        ids.append("NAR")
    if project.audio.voiceover:
        ids.append("VO")
    if project.audio.music is not None:
        ids.append("MUS")
    ids.append("SFX")
    return ids


def silenced_audio_tracks(project: Project) -> set[str]:
    """As trilhas de áudio que não soam: as mudas e, havendo alguma em solo, todas as que não estão em solo (como no
    Audacity). É a única regra de solo: a vista e o render leem daqui, e a prévia e o vídeo nunca discordam."""
    tracks = project.tracks
    ids = audio_track_ids(project)
    soloed = {track_id for track_id in ids if track_id in tracks and tracks[track_id].solo}
    return {track_id for track_id in ids if _muted(tracks, track_id) or (soloed and track_id not in soloed)}


def _renumbered_externals(project: Project, silenced: set[str]) -> dict[str, str]:
    """Para cada faixa externa que sobra, o id que ela passa a ter: tirar a A2 faz a A3 virar a A2, porque `audio.tracks` é
    uma lista e a vista conta pela posição. É a conta que o Auto Duck e a portadora do Vocoder dividem."""
    kept = [i for i in range(len(project.audio.tracks)) if f"A{2 + i}" not in silenced]
    return {f"A{2 + old}": f"A{2 + new}" for new, old in enumerate(kept)}


def _ducks_after_state(project: Project, audio, silenced: set[str]):
    """As regras do Auto Duck depois do mudo e do solo: uma regra cuja trilha (a que abaixa ou a que comanda) não soa
    deixa de valer, e os ids das faixas externas acompanham a lista que sobrou (tirar a A2 faz a A3 virar a A2, como
    `audio.tracks` acima)."""
    if not project.audio.ducks:
        return audio
    renamed = _renumbered_externals(project, silenced)
    rules = []
    for rule in project.audio.ducks:
        if rule.background in silenced or rule.key in silenced:
            continue
        background, key = renamed.get(rule.background, rule.background), renamed.get(rule.key, rule.key)
        rules.append(
            rule
            if (background, key) == (rule.background, rule.key)
            else rule.model_copy(update={"background": background, "key": key})
        )
    return audio if rules == audio.ducks else audio.model_copy(update={"ducks": rules})


def apply_track_state(project: Project) -> Project:
    """Spec equivalente com o mudo/solo/ganho/pan/oculto de `project.tracks` já embutido nos campos que o render
    realmente olha, para o resto do pipeline não precisar saber que trilhas da interface existem:

    - A1 muda -> `audio.mute_clips = True` (mudo do áudio de cada clipe da V1); o ganho e o pan dela entram no
      `volume` e no `pan` de cada clipe.
    - A<n> muda, n>=2 -> remove `audio.tracks[n-2]` (a faixa externa some da mixagem); o ganho e o pan entram
      no `volume` e no `pan` da faixa.
    - MUS muda -> `audio.music = None`; NAR muda -> `audio.narration = []`; VO muda -> `audio.voiceover = []`;
      o ganho e o pan entram no `volume` e no `pan` de cada item.
    - SFX muda -> `audio.sfx_gain_db` cai para -120 dB; o ganho e o pan entram em `sfx_gain_db` e `sfx_pan`.
    - Solo: com alguma trilha de áudio em solo, as outras trilhas de áudio contam como mudas
      (`silenced_audio_tracks`).
    - CC oculta -> `captions.enabled = False`.
    - TX oculta -> remove as sobreposições de texto.
    - GR oculta -> remove as sobreposições de imagem e de composição HTML e a barra de progresso.
    - V<n> oculta, n>=2 -> remove as sobreposições de vídeo (PiP) daquela faixa
      (`video_overlay_lanes` decide qual PiP é de qual faixa).
    - V1 oculta é ignorada (é a linha do tempo principal; não há como renderizar sem ela) e
      `locked` nunca muda o render, só a edição na interface.

    O ganho em dB multiplica o `volume` do item e o pan soma ao do item, preso a -1..1. Nunca modifica
    `project`; devolve o mesmo objeto quando não há nada a aplicar."""
    tracks = project.tracks
    if not tracks:
        return project

    silenced = silenced_audio_tracks(project)
    audio = project.audio
    timeline = project.timeline

    a1 = tracks.get("A1")
    if "A1" in silenced and not audio.mute_clips:
        audio = audio.model_copy(update={"mute_clips": True})
    if a1 and (a1.gain_db or a1.pan):
        timeline = [_mixed(seg, a1) if isinstance(seg, ClipSegment) else seg for seg in timeline]

    remaining_tracks = [
        _mixed(track, tracks.get(f"A{2 + i}"))
        for i, track in enumerate(audio.tracks)
        if f"A{2 + i}" not in silenced
    ]
    if remaining_tracks != audio.tracks:
        audio = audio.model_copy(update={"tracks": remaining_tracks})

    if audio.music is not None:
        music = None if "MUS" in silenced else _mixed(audio.music, tracks.get("MUS"))
        if music is not audio.music:
            audio = audio.model_copy(update={"music": music})

    if audio.narration:
        narration = [] if "NAR" in silenced else [_mixed(item, tracks.get("NAR")) for item in audio.narration]
        if narration != audio.narration:
            audio = audio.model_copy(update={"narration": narration})

    if audio.voiceover:
        voiceover = [] if "VO" in silenced else [_mixed(item, tracks.get("VO")) for item in audio.voiceover]
        if voiceover != audio.voiceover:
            audio = audio.model_copy(update={"voiceover": voiceover})

    sfx = tracks.get("SFX")
    if "SFX" in silenced or (sfx and (sfx.gain_db or sfx.pan)):
        gain = SILENT_GAIN_DB if "SFX" in silenced else audio.sfx_gain_db + (sfx.gain_db if sfx else 0.0)
        pan = _summed_pan(audio.sfx_pan, sfx.pan if sfx else 0.0)
        if (gain, pan) != (audio.sfx_gain_db, audio.sfx_pan):
            audio = audio.model_copy(update={"sfx_gain_db": gain, "sfx_pan": pan})

    audio = _ducks_after_state(project, audio, silenced)
    audio, timeline = _carriers_after_state(project, audio, timeline, silenced)

    captions = project.captions
    if _hidden(tracks, "CC") and captions is not None and captions.enabled:
        captions = captions.model_copy(update={"enabled": False})

    overlays = project.overlays
    tx_hidden = _hidden(tracks, "TX")
    gr_hidden = _hidden(tracks, "GR")
    hidden_lanes = {
        int(track_id[1:]) - 2
        for track_id, state in tracks.items()
        if state.hidden and track_id != "V1" and track_id.startswith("V") and track_id[1:].isdigit()
    }
    if tx_hidden or gr_hidden or hidden_lanes:
        lanes = video_overlay_lanes(project) if hidden_lanes else {}
        overlays = [
            ov
            for i, ov in enumerate(overlays)
            if not (tx_hidden and isinstance(ov, TextOverlay))
            and not (gr_hidden and isinstance(ov, ImageOverlay | HtmlOverlay | ProgressBar))
            and not (isinstance(ov, VideoOverlay) and lanes.get(i) in hidden_lanes)
        ]

    if (
        audio is project.audio
        and captions is project.captions
        and overlays is project.overlays
        and timeline is project.timeline
    ):
        return project
    updated = project.model_copy(
        update={"audio": audio, "captions": captions, "overlays": overlays, "timeline": timeline}
    )
    updated.base_dir = project.base_dir
    return updated


def _carrier_effects(effects: list, silenced: set[str], renamed: dict[str, str]) -> list:
    """A cadeia com a trilha portadora de cada efeito posta no estado: a que não soa vira `None` (o efeito usa a portadora
    gerada) e a de faixa externa segue a renumeração. Devolve a própria lista quando nada muda."""
    result = []
    for effect in effects:
        carrier = effect.carrier_track_id()
        if carrier is not None:
            target = None if carrier in silenced else renamed.get(carrier, carrier)
            if target != carrier:
                effect = effect.model_copy(update={"carrier_track": target})
        result.append(effect)
    return effects if all(new is old for new, old in zip(result, effects, strict=True)) else result


def _carriers_after_state(project: Project, audio, timeline, silenced: set[str]):
    """Os itens que sobraram com a portadora do Vocoder acompanhando o mudo e o solo: a trilha que não soa não pode ser
    ouvida (o id dela passaria a apontar para outra fonte, ou para um barramento calado) e as demais seguem a renumeração das
    faixas externas. Sem `carrier_track` em lugar nenhum devolve os mesmos objetos."""
    if not any(
        effect.carrier_track_id() is not None
        for _, _, effects in project.carrier_hosts()
        for effect in effects
    ):
        return audio, timeline
    renamed = _renumbered_externals(project, silenced)

    def fixed(item):
        effects = _carrier_effects(item.effects, silenced, renamed)
        return item if effects is item.effects else item.model_copy(update={"effects": effects})

    timeline = [fixed(seg) if isinstance(seg, ClipSegment) else seg for seg in timeline]
    update = {}
    for name in ("tracks", "narration", "voiceover", "generated"):
        items = getattr(audio, name)
        new = [fixed(item) for item in items]
        if any(a is not b for a, b in zip(new, items, strict=True)):
            update[name] = new
    if audio.music is not None and fixed(audio.music) is not audio.music:
        update["music"] = fixed(audio.music)
    return (audio.model_copy(update=update) if update else audio), timeline


def silenced_carrier_warnings(project: Project) -> list[str]:
    """Um aviso por item cujo Vocoder pede a portadora de uma trilha que está muda ou fora do solo: o efeito usa a portadora
    gerada. Lê o projeto ANTES do estado, porque depois dele o campo já foi trocado por vazio."""
    silenced = silenced_audio_tracks(project)
    return [
        f"{place}: o Vocoder pede a portadora da trilha {carrier}, que está muda ou fora do solo; usa a portadora gerada."
        for host, place, effects in project.carrier_hosts()
        if host not in silenced  # o item de uma trilha que não soa não vai a lugar nenhum: nada a avisar
        for effect in effects
        if effect.enabled and (carrier := effect.carrier_track_id()) in silenced
    ]


def _summed_pan(first: float, second: float) -> float:
    """O pan de um item mais o da trilha dele, preso ao intervalo -1..1."""
    return max(-1.0, min(1.0, first + second))


def _mixed(item, state):
    """O item com o ganho e o pan da trilha embutidos (o ganho em dB multiplica o `volume`). Sem ganho nem pan na
    trilha devolve o próprio item, para a spec seguir idêntica."""
    if state is None or not (state.gain_db or state.pan):
        return item
    update = {}
    if state.gain_db:
        update["volume"] = item.volume * 10 ** (state.gain_db / 20)
    if state.pan:
        update["pan"] = _summed_pan(item.pan, state.pan)
    return item.model_copy(update=update)


def _muted(tracks: dict, track_id: str) -> bool:
    state = tracks.get(track_id)
    return bool(state and state.muted)


def _hidden(tracks: dict, track_id: str) -> bool:
    state = tracks.get(track_id)
    return bool(state and state.hidden)
