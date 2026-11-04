"""Gravação pelo microfone no servidor: pedaços numerados, reenvio sem duplicar, recuperação da aba que fechou e a
operação que põe a gravação na spec. O navegador é trocado por um cliente de teste que manda os pedaços."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media.wavio import read_wav_float
from dmaker.pipeline.recordings import (
    RecordingError,
    RecordingStore,
    edit_for_recording,
    missing_chunks,
)
from dmaker.ui import server

RATE = 8000  # a taxa baixa só encurta o teste: o servidor não depende dela


def tone(seconds: float, rate: int = RATE, hz: float = 440.0, start: float = 0.0) -> bytes:
    t = np.arange(round(seconds * rate)) / rate + start
    return (0.5 * np.sin(2 * np.pi * hz * t)).astype("<f4").tobytes()


@pytest.fixture
def project_dir():
    folder = config.PROJECTS_DIR / "gravacao"
    folder.mkdir(parents=True)
    (folder / "spec.json").write_text(
        Project.model_validate(
            {"name": "gravacao", "output": {"preset": "audio/wav"}, "timeline": []}
        ).model_dump_json(exclude_none=True),
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def client(project_dir):
    with TestClient(server.app) as c:
        yield c


def open_recording(client, **body) -> str:
    response = client.post("/api/projects/gravacao/recordings", json={"rate": RATE, "channels": 1, **body})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def send(client, identifier: str, seq: int, data: bytes):
    return client.put(
        f"/api/projects/gravacao/recordings/{identifier}/chunks/{seq}",
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_pedacos_chegam_numerados_e_o_finish_junta_num_wav(client, project_dir):
    identifier = open_recording(client, start=2.5, label="Narração")
    for seq in range(3):
        assert send(client, identifier, seq, tone(1.0, start=seq)).status_code == 200
    body = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    assert body["state"] == "finished" and body["duration"] == pytest.approx(3.0)
    assert body["gaps"] == [] and body["src"] == f"recordings/{identifier}/gravacao.wav"
    assert body["op"] == {
        "type": "audio_record_add",
        "src": body["src"],
        "start": 2.5,
        "duration": 3.0,
    }
    samples, rate = _read_float_wav(project_dir / body["src"])
    assert rate == RATE and len(samples) == 3 * RATE
    expected = np.frombuffer(b"".join(tone(1.0, start=s) for s in range(3)), dtype="<f4")
    assert np.allclose(samples[:, 0], expected)
    # os pedaços saem do disco depois de juntados
    assert not list((project_dir / "recordings" / identifier).glob("*.f32"))


def test_reenviar_o_mesmo_pedaco_nao_duplica(client, project_dir):
    identifier = open_recording(client)
    first = send(client, identifier, 0, tone(1.0)).json()
    again = send(client, identifier, 0, tone(1.0)).json()
    send(client, identifier, 1, tone(1.0))
    assert first["duplicate"] is False and again["duplicate"] is True
    body = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    assert body["duration"] == pytest.approx(2.0)


def test_pedaco_que_falta_vira_silencio_e_a_resposta_diz_qual(client, project_dir):
    identifier = open_recording(client)
    send(client, identifier, 0, tone(1.0))
    send(client, identifier, 2, tone(1.0))
    body = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    assert body["gaps"] == [1] and body["duration"] == pytest.approx(3.0)
    samples, _ = _read_float_wav(project_dir / body["src"])
    assert np.all(samples[RATE : 2 * RATE] == 0)


def test_10_minutos_com_a_aba_fechada_no_meio_ficam_salvos_e_recuperaveis(client, project_dir):
    """O cliente manda 6 minutos de pedaços e some (a aba fechou, sem `finish`). Tudo o que chegou está no disco, a
    gravação aparece na lista das não finalizadas e a recuperação devolve a duração certa."""
    identifier = open_recording(client, start=1.0)
    sent = 360  # 6 de 10 minutos
    chunk = tone(1.0)
    for seq in range(sent):
        assert send(client, identifier, seq, chunk).status_code == 200
    # a "nova sessão": só o disco e a lista
    listed = client.get("/api/projects/gravacao/recordings", params={"unfinished": True}).json()["recordings"]
    assert [item["id"] for item in listed] == [identifier]
    assert listed[0]["state"] == "open" and listed[0]["chunks"] == sent
    assert listed[0]["duration"] == pytest.approx(sent)
    recovered = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    assert recovered["duration"] == pytest.approx(sent) and recovered["gaps"] == []
    assert recovered["frames"] == sent * RATE
    assert recovered["recover_op"]["type"] == "audio_record_add"
    after = client.get("/api/projects/gravacao/recordings", params={"unfinished": True}).json()["recordings"]
    assert after == []


def test_finish_repetido_devolve_a_mesma_resposta(client):
    identifier = open_recording(client)
    send(client, identifier, 0, tone(1.0))
    first = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    second = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    assert first == second


def test_gravacao_finalizada_nao_recebe_pedaco(client):
    identifier = open_recording(client)
    send(client, identifier, 0, tone(1.0))
    client.post(f"/api/projects/gravacao/recordings/{identifier}/finish")
    assert send(client, identifier, 1, tone(1.0)).status_code == 400


def test_pedaco_quebrado_e_recusado(client):
    identifier = open_recording(client, channels=2)
    assert send(client, identifier, 0, b"\x00" * 6).status_code == 400  # não são quadros inteiros de 2 canais
    assert send(client, identifier, 0, b"").status_code == 400
    assert send(client, identifier, -1, tone(1.0)).status_code == 400


def test_formato_invalido_e_recusado(client):
    assert (
        client.post("/api/projects/gravacao/recordings", json={"rate": 10, "channels": 1}).status_code == 400
    )
    assert (
        client.post("/api/projects/gravacao/recordings", json={"rate": RATE, "channels": 5}).status_code
        == 400
    )


def test_projeto_inexistente_ou_nome_perigoso(client):
    assert client.post("/api/projects/nao-existe/recordings", json={"rate": RATE}).status_code == 404
    assert client.get("/api/projects/..%2F..%2Fx/recordings").status_code in (400, 404)


def test_finish_sem_pedaco_e_recusado(client):
    identifier = open_recording(client)
    assert client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").status_code == 400


def test_descartar_so_vale_para_gravacao_aberta(client, project_dir):
    aberta = open_recording(client)
    send(client, aberta, 0, tone(1.0))
    assert client.delete(f"/api/projects/gravacao/recordings/{aberta}").status_code == 200
    assert not (project_dir / "recordings" / aberta).exists()
    fechada = open_recording(client)
    send(client, fechada, 0, tone(1.0))
    client.post(f"/api/projects/gravacao/recordings/{fechada}/finish")
    assert client.delete(f"/api/projects/gravacao/recordings/{fechada}").status_code == 400


def test_punch_in_devolve_a_operacao_do_punch(client):
    identifier = open_recording(
        client, start=3.0, punch={"target": "audio.voiceover.0", "start": 4.0, "end": 7.0}, label="Take 2"
    )
    for seq in range(5):
        send(client, identifier, seq, tone(1.0))
    body = client.post(f"/api/projects/gravacao/recordings/{identifier}/finish").json()
    assert body["op"]["type"] == "audio_punch"
    assert (body["op"]["start"], body["op"]["end"], body["op"]["recorded_at"]) == (4.0, 7.0, 3.0)
    assert body["recover_op"]["type"] == "audio_record_add"  # recuperar sempre põe uma voz nova


def test_o_finish_pode_corrigir_o_instante_e_o_alvo(client):
    identifier = open_recording(
        client, start=3.0, punch={"target": "audio.voiceover.0", "start": 4, "end": 7}
    )
    send(client, identifier, 0, tone(1.0))
    body = client.post(
        f"/api/projects/gravacao/recordings/{identifier}/finish",
        json={"start": 3.012, "punch": {"target": "audio.voiceover.2", "start": 4, "end": 7}},
    ).json()
    assert body["start"] == 3.012 and body["op"]["target"] == "audio.voiceover.2"


def test_missing_chunks_e_funcao_pura():
    assert missing_chunks(set()) == ()
    assert missing_chunks({0, 1, 2}) == ()
    assert missing_chunks({0, 3, 5}) == (1, 2, 4)


def test_edit_for_recording_recusa_gravacao_aberta(project_dir):
    store = RecordingStore(project_dir)
    status = store.create(RATE, 1)
    with pytest.raises(RecordingError, match="finalizada"):
        edit_for_recording(status)


def _read_float_wav(path):
    """Lê o WAV float32 que o servidor escreve (o leitor de 16 bits da suíte não serve)."""
    return read_wav_float(path)
