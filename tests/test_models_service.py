"""Gerenciador de modelos: inventário medido, sobras, baixar com progresso e apagar com confirmação.

Tudo roda numa pasta temporária com modelos de mentira (um registro pequeno e funções de download falsas);
nada aqui toca o `cache/models` de verdade.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from dmaker.domain.models import ModelSpec
from dmaker.pipeline.models_service import (
    ConfirmationRequired,
    InsufficientSpace,
    ModelBusy,
    ModelError,
    ModelService,
    UnknownModel,
    _inside,
    find_leftovers,
    measure_path,
)

BIG = 1000  # bytes de um modelo "inteiro" nos testes


def make_spec(model_id: str, *paths: str, expected: int = BIG, fetch: str = "fake:fetch") -> ModelSpec:
    return ModelSpec(
        id=model_id,
        name=model_id.upper(),
        purpose="serve para testar",
        engine="teste",
        license="MIT",
        paths=paths,
        expected_size=expected,
        required_by=(f"função de {model_id}",),
        fetch=fetch,
    )


ALPHA = make_spec("alpha", "alpha")
BETA = make_spec("beta", "beta.onnx", expected=200)
# dois modelos que dividem o arquivo de vozes, como o Kokoro
FAST = make_spec("fast", "kokoro/fast.onnx", "kokoro/voices.bin", expected=600)
SMALL = make_spec("small", "kokoro/small.onnx", "kokoro/voices.bin", expected=300)
SPECS = (ALPHA, BETA, FAST, SMALL)


def write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    return folder


def service_for(models_dir: Path, fetchers=None, free: int | None = 10**9, **kwargs) -> ModelService:
    fetchers = fetchers or {}
    return ModelService(
        models_dir,
        SPECS,
        fetcher_for=lambda dotted: fetchers[dotted],
        disk_free=lambda path: free,
        poll_seconds=0.01,
        **kwargs,
    )


def states(service: ModelService) -> dict[str, str]:
    return {status.spec.id: status.state for status in service.inventory().models}


# ---------- medir ----------


def test_measure_counts_files_recursively_and_flags_unfinished_downloads(tmp_path: Path):
    write(tmp_path / "a" / "um.bin", 100)
    write(tmp_path / "a" / "b" / "dois.bin", 50)
    mark = measure_path(tmp_path / "a")
    assert (mark.size, mark.exists, mark.incomplete) == (150, True, False)
    write(tmp_path / "a" / "b" / "grande.bin.incomplete", 10)
    assert measure_path(tmp_path / "a").incomplete
    missing = measure_path(tmp_path / "nada")
    assert (missing.size, missing.exists, missing.incomplete) == (0, False, False)


# ---------- inventário ----------


def test_inventory_reports_state_and_real_size_of_each_model(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    write(models_dir / "beta.onnx", 50)  # 25% do esperado: pela metade
    inventory = service_for(models_dir).inventory()
    by_id = {status.spec.id: status for status in inventory.models}
    assert (by_id["alpha"].state, by_id["alpha"].size_bytes) == ("installed", BIG)
    assert (by_id["beta"].state, by_id["beta"].size_bytes) == ("partial", 50)
    assert (by_id["fast"].state, by_id["fast"].size_bytes) == ("absent", 0)
    assert inventory.total_bytes == BIG + 50
    assert inventory.disk_free_bytes == 10**9
    payload = inventory.to_dict()
    assert payload["total_bytes"] == BIG + 50 and payload["total_label"] == "1 KB"
    assert payload["models"][0]["id"] == "alpha" and payload["models"][0]["license"] == "MIT"
    assert payload["models"][0]["size_label"] == "1000 B" and payload["disk_free_label"] == "953,7 MB"


def test_a_leftover_download_file_makes_an_otherwise_full_model_partial(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    write(models_dir / "alpha" / "resto.incomplete", 1)
    assert states(service_for(models_dir))["alpha"] == "partial"


def test_a_shared_file_alone_does_not_make_the_other_model_look_installed(models_dir: Path):
    write(models_dir / "kokoro" / "voices.bin", 300)
    write(models_dir / "kokoro" / "small.onnx", 300)
    found = states(service_for(models_dir))
    assert found["small"] == "installed" and found["fast"] == "absent"


def test_the_models_dir_is_read_when_used_not_when_the_service_is_built(tmp_path: Path, monkeypatch):
    from dmaker import config

    service = ModelService(specs=SPECS)
    first, second = tmp_path / "um", tmp_path / "dois"
    write(first / "alpha" / "p.bin", BIG)
    monkeypatch.setattr(config, "MODELS_DIR", first)
    assert states(service)["alpha"] == "installed"
    monkeypatch.setattr(config, "MODELS_DIR", second)
    assert states(service)["alpha"] == "absent"


# ---------- sobras ----------


def test_leftovers_are_what_no_model_claims_and_the_hf_bookkeeping_is_ignored(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    write(models_dir / "kokoro" / "fast.onnx", 10)
    write(models_dir / "kokoro" / "velho.onnx", 30)  # solto dentro da pasta de um modelo
    write(models_dir / "audioseal" / "x.bin", 70)
    write(models_dir / "arquivo-solto.txt", 5)
    (models_dir / ".locks" / "alpha").mkdir(parents=True)
    write(models_dir / "CACHEDIR.TAG", 3)
    found = {item.path: (item.size_bytes, item.is_dir) for item in find_leftovers(models_dir, SPECS)}
    assert found == {
        "arquivo-solto.txt": (5, False),
        "audioseal": (70, True),
        "kokoro/velho.onnx": (30, False),
    }


def test_a_download_in_progress_is_not_a_leftover(models_dir: Path):
    write(models_dir / "kokoro" / "fast.onnx.part", 10)
    write(models_dir / "beta.part", 10)  # o matting troca .onnx por .part
    write(models_dir / "alpha" / "blobs" / "abc.incomplete", 10)
    assert find_leftovers(models_dir, SPECS) == []


def test_prune_needs_confirmation_and_deletes_only_the_leftovers(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    write(models_dir / "beta.onnx", 200)
    write(models_dir / "sobra" / "um.bin", 40)
    write(models_dir / "sobra" / "fundo" / "dois.bin", 60)
    write(models_dir / "solto.bin", 7)
    service = service_for(models_dir)
    with pytest.raises(ConfirmationRequired, match="2 item"):
        service.prune()
    assert (models_dir / "sobra").exists()
    plan = service.prune(confirm=True)
    assert sorted(plan.paths) == ["sobra", "solto.bin"] and plan.freed_bytes == 107
    assert not (models_dir / "sobra").exists() and not (models_dir / "solto.bin").exists()
    assert (models_dir / "alpha" / "peso.bin").exists() and (models_dir / "beta.onnx").exists()
    assert service.plan_prune().paths == []


def test_prune_with_a_list_only_touches_what_the_person_saw(models_dir: Path):
    write(models_dir / "visto" / "a.bin", 1)
    write(models_dir / "novo" / "b.bin", 1)  # apareceu depois de a pessoa abrir a lista
    write(models_dir / "alpha" / "peso.bin", BIG)
    service = service_for(models_dir)
    plan = service.prune(confirm=True, only=["visto", "alpha"])  # "alpha" é modelo: não é sobra, não entra
    assert plan.paths == ["visto"]
    assert (models_dir / "novo").exists() and (models_dir / "alpha").exists()


# ---------- apagar um modelo ----------


def test_remove_warns_which_functions_stop_working_and_needs_confirmation(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    service = service_for(models_dir)
    plan = service.plan_removal("alpha")
    assert plan.stops_working == ["função de alpha"] and plan.freed_bytes == BIG
    assert "função de alpha" in plan.warning() and "ALPHA" in plan.warning()
    with pytest.raises(ConfirmationRequired, match="função de alpha"):
        service.remove("alpha")
    assert (models_dir / "alpha" / "peso.bin").exists()
    service.remove("alpha", confirm=True)
    assert not (models_dir / "alpha").exists()
    with pytest.raises(ModelError, match="não está baixado"):
        service.remove("alpha", confirm=True)


def test_remove_keeps_the_shared_file_while_the_other_model_is_installed(models_dir: Path):
    write(models_dir / "kokoro" / "fast.onnx", 300)
    write(models_dir / "kokoro" / "small.onnx", 100)
    write(models_dir / "kokoro" / "voices.bin", 200)
    service = service_for(models_dir)
    assert service.plan_removal("fast").paths == ["kokoro/fast.onnx"]
    service.remove("fast", confirm=True)
    assert (models_dir / "kokoro" / "voices.bin").exists() and (models_dir / "kokoro" / "small.onnx").exists()
    # o último a sair leva o arquivo dividido junto
    assert sorted(service.plan_removal("small").paths) == ["kokoro/small.onnx", "kokoro/voices.bin"]
    service.remove("small", confirm=True)
    assert not (models_dir / "kokoro" / "voices.bin").exists()


def test_remove_also_clears_the_part_file_of_an_interrupted_download(models_dir: Path):
    write(models_dir / "kokoro" / "fast.onnx.part", 40)
    service = service_for(models_dir)
    assert service.plan_removal("fast").paths == ["kokoro/fast.onnx.part"]
    service.remove("fast", confirm=True)
    assert not (models_dir / "kokoro" / "fast.onnx.part").exists()


def test_removing_never_touches_other_models_or_the_leftovers(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)
    write(models_dir / "beta.onnx", 200)
    write(models_dir / "sobra" / "x.bin", 9)
    service_for(models_dir).remove("alpha", confirm=True)
    assert (models_dir / "beta.onnx").exists() and (models_dir / "sobra" / "x.bin").exists()


def test_unknown_model_is_reported_with_the_known_ids(models_dir: Path):
    service = service_for(models_dir)
    for call in (service.status, service.plan_removal, service.download):
        with pytest.raises(UnknownModel, match="alpha, beta"):
            call("fantasma")


# ---------- segurança do apagar ----------


@pytest.mark.parametrize("relative", ["..", "../fora", "a/../../fora", "/abs", "C:/Windows", "a\\..\\b", ""])
def test_inside_refuses_any_path_that_could_leave_the_models_dir(models_dir: Path, relative: str):
    with pytest.raises(ModelError, match="fora de cache/models"):
        _inside(models_dir, relative)


def test_inside_accepts_a_nested_path_under_the_models_dir(models_dir: Path):
    assert _inside(models_dir, "kokoro/voices.bin") == models_dir.resolve() / "kokoro" / "voices.bin"


def test_a_registry_with_a_tampered_path_is_stopped_before_deleting_anything(tmp_path: Path):
    """Mesmo que um `ModelSpec` chegue com caminho fora da pasta (mutação, extensão mal feita), o apagar recusa."""
    victim = write(tmp_path / "importante.txt", 5)
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    evil = make_spec("evil", "ok")
    object.__setattr__(evil, "paths", ("../importante.txt",))
    service = ModelService(models_dir, (evil,), disk_free=lambda path: None)
    with pytest.raises(ModelError, match="fora de cache/models"):
        service.remove("evil", confirm=True)
    assert victim.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="junção é coisa do Windows")
def test_deleting_a_folder_with_a_junction_inside_does_not_touch_the_junction_target(
    models_dir: Path, tmp_path: Path
):
    target = tmp_path / "fora"
    write(target / "precioso.bin", 8)
    write(models_dir / "sobra" / "x.bin", 1)
    link = models_dir / "sobra" / "atalho"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    service_for(models_dir).prune(confirm=True)
    assert not (models_dir / "sobra").exists()
    assert (target / "precioso.bin").read_bytes() == b"x" * 8


@pytest.mark.skipif(sys.platform != "win32", reason="junção é coisa do Windows")
def test_a_model_folder_that_is_a_link_is_never_deleted(models_dir: Path, tmp_path: Path):
    """Quem move um modelo para outro disco com um link não pode perder o modelo ao clicar em Apagar."""
    target = tmp_path / "outro-disco"
    write(target / "peso.bin", BIG)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(models_dir / "alpha"), str(target)], check=True, capture_output=True
    )
    service = service_for(models_dir)
    assert states(service)["alpha"] == "installed"  # mede o destino do link
    with pytest.raises(ModelError, match="atalho"):
        service.remove("alpha", confirm=True)
    assert (target / "peso.bin").exists()


def test_read_only_files_are_deleted_too(models_dir: Path):
    path = write(models_dir / "sobra" / "ro.bin", 3)
    os.chmod(path, 0o444)
    service_for(models_dir).prune(confirm=True)
    assert not (models_dir / "sobra").exists()


# ---------- baixar ----------


def test_download_reports_progress_from_the_disk_and_checks_the_result(models_dir: Path):
    def fetch(directory: Path, variant: str) -> None:
        for step in range(1, 5):
            write(directory / "alpha" / "peso.bin", 250 * step)
            threading.Event().wait(0.05)  # dá tempo ao medidor de ver cada passo

    service = service_for(models_dir, {"fake:fetch": fetch})
    seen: list[tuple[int, int]] = []
    status = service.download("alpha", lambda done, total: seen.append((done, total)))
    assert status.state == "installed" and status.size_bytes == BIG
    assert seen[0] == (0, BIG) and seen[-1] == (BIG, BIG)
    assert any(0 < done < BIG for done, _ in seen), seen  # houve avanço no meio do caminho
    assert [done for done, _ in seen] == sorted(done for done, _ in seen)


def test_a_part_file_counts_in_the_size_and_makes_the_model_partial(models_dir: Path):
    """O Kokoro e o matting baixam para um `.part` e só renomeiam no fim: sem contá-lo a barra ficaria em 0%."""
    write(models_dir / "kokoro" / "fast.onnx.part", 123)
    status = service_for(models_dir).status("fast")
    assert (status.state, status.size_bytes) == ("partial", 123)
    assert states(service_for(models_dir))["small"] == "absent"  # o .part do outro não faz este existir


def test_download_progress_follows_a_part_file_that_is_renamed_at_the_end(models_dir: Path):
    def fetch(directory: Path, variant: str) -> None:
        partial = directory / "beta.onnx.part"
        for step in range(1, 5):
            write(partial, 50 * step)
            threading.Event().wait(0.05)
        partial.replace(directory / "beta.onnx")

    seen: list[int] = []
    service = service_for(models_dir, {"fake:fetch": fetch})
    service.download("beta", lambda done, total: seen.append(done))
    assert any(0 < done < 200 for done in seen), seen
    assert seen[-1] == 200 and not (models_dir / "beta.onnx.part").exists()


def test_download_passes_the_variant_and_the_models_dir_to_the_fetcher(models_dir: Path):
    calls = []
    spec = ModelSpec("v", "V", "p", "e", "MIT", ("v",), 10, ("f",), "fake:fetch", variant="int8")
    service = ModelService(
        models_dir,
        (spec,),
        fetcher_for=lambda dotted: (
            lambda directory, variant: (
                calls.append((dotted, directory, variant)),
                write(directory / "v", 10),
            )
        ),
        disk_free=lambda path: 10**9,
    )
    service.download("v")
    assert calls == [("fake:fetch", models_dir, "int8")]


def test_download_of_an_installed_model_does_nothing(models_dir: Path):
    write(models_dir / "alpha" / "peso.bin", BIG)

    def fetch(directory: Path, variant: str) -> None:
        raise AssertionError("não devia baixar de novo")

    assert service_for(models_dir, {"fake:fetch": fetch}).download("alpha").state == "installed"


def test_download_fails_when_the_fetcher_leaves_the_model_incomplete(models_dir: Path):
    service = service_for(
        models_dir, {"fake:fetch": lambda directory, variant: write(directory / "alpha" / "p", 10)}
    )
    with pytest.raises(ModelError, match="incompletos"):
        service.download("alpha")


def test_download_propagates_the_fetcher_error_and_releases_the_model(models_dir: Path):
    def fetch(directory: Path, variant: str) -> None:
        raise ConnectionError("sem internet")

    service = service_for(models_dir, {"fake:fetch": fetch})
    with pytest.raises(ConnectionError):
        service.download("alpha")
    with pytest.raises(ConnectionError):  # o modelo não ficou preso como "baixando"
        service.download("alpha")


def test_download_refuses_when_the_disk_is_too_full(models_dir: Path):
    write(models_dir / "alpha" / "p", 100)  # já tem 100 de 1000: faltam 900
    service = service_for(models_dir, {"fake:fetch": lambda d, v: None}, free=500)
    with pytest.raises(InsufficientSpace, match="Falta espaço"):
        service.download("alpha")


def test_two_downloads_of_the_same_model_do_not_run_together(models_dir: Path):
    started, release = threading.Event(), threading.Event()

    def fetch(directory: Path, variant: str) -> None:
        started.set()
        release.wait(5)
        write(directory / "alpha" / "p", BIG)

    service = service_for(models_dir, {"fake:fetch": fetch})
    worker = threading.Thread(target=service.download, args=("alpha",))
    worker.start()
    assert started.wait(5)
    try:
        with pytest.raises(ModelBusy):
            service.download("alpha")
        with pytest.raises(ModelBusy):  # nem apagar o que está sendo baixado, nem limpar sobras no meio
            service.remove("alpha", confirm=True)
        with pytest.raises(ModelBusy):
            service.prune(confirm=True)
    finally:
        release.set()
        worker.join(5)
    assert states(service)["alpha"] == "installed"
