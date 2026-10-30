"""Anexos da conversa com o agente: receber o arquivo, guardá-lo e entregá-lo ao turno que o envia.

É a camada entre o upload HTTP e `agent/attachments.py` (puro). O anexo nasce numa conversa que já existe, antes da
mensagem: a tela o envia, mostra a ficha e só então manda a mensagem com os ids. Cada tipo vai para um lugar:

- texto extraído fica em `conversations/<id>/` (some junto com a conversa), com o nome do anexo no arquivo;
- vídeo, áudio e planilha vão para `cache/uploads` pela mesma função do upload de fala (as ferramentas leem por
  caminho, e enviar o mesmo arquivo de novo reaproveita o caminho e os caches por caminho);
- a imagem vai para onde a conversa a usa: numa conversa que opera o DMaker ela é arquivo de trabalho e segue para
  `cache/uploads` como o vídeo, para a foto entrar num projeto; numa conversa livre só o modelo a vê, e ela fica na
  pasta da conversa. O modo pode mudar até a primeira mensagem, então quem manda é o modo do envio: a imagem que
  nasceu na pasta da conversa ganha a cópia de trabalho quando a mensagem vai para quem opera.

Os limites de tamanho são por tipo e a recusa diz qual é o limite. O leitor de planilha entra por parâmetro.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..agent.attachments import (
    EXCERPT_CHARS,
    KIND_IMAGE,
    KIND_MEDIA,
    KIND_SHEET,
    KIND_TEXT,
    MAX_ATTACHMENTS_PER_MESSAGE,
    AttachedFile,
    AttachmentRecord,
    AttachmentRefused,
    classify,
    image_mime,
    image_signature_matches,
    sheet_preview,
)
from ..agent.conversations import MODE_FREE, MODE_OPERATE, settings_for_conversation
from ..agent.settings import AgentSettings
from ..agent.transcript import utc_now
from ..domain.batch_sheet import Sheet, SheetError
from ..pipeline.batch_files import read_sheet
from ..text.documents import (
    EXTRACTORS,
    MAX_EXTRACTED_CHARS,
    DocumentError,
    extract_plain,
    extract_text,
)
from .agent_conversations import Conversation
from .uploads import MAX_UPLOAD_BYTES, media_upload_dir, read_upload, save_upload, upload_file_name

MIB = 1024 * 1024
MAX_IMAGE_BYTES = 20 * MIB  # uma foto de celular tem poucos MB; o modelo reduz a imagem de qualquer jeito
MAX_DOCUMENT_BYTES = 25 * MIB  # um Word com figuras pode pesar, mas o texto dele é pequeno
MAX_SHEET_BYTES = 50 * MIB
MAX_NAME_CHARS = 120
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Um .csv que não tem forma de planilha ainda é texto que se lê: só aqui o .csv ganha um extrator.
CSV_AS_TEXT = {**EXTRACTORS, ".csv": extract_plain}

SheetReader = Callable[[Path], Sheet]
OpenConversation = Callable[[str, AgentSettings], Conversation]


def display_name(upload: UploadFile) -> str:
    """O nome que a tela mostra: o do arquivo enviado, sem pasta nem caractere de controle."""
    raw = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _CONTROL.sub(" ", raw).strip()
    return (cleaned or "arquivo")[:MAX_NAME_CHARS]


def size_limit(kind: str) -> tuple[int, str]:
    """O limite de tamanho do tipo e o nome dele para a mensagem; lido na hora para os testes poderem encolhê-lo."""
    return {
        KIND_IMAGE: (MAX_IMAGE_BYTES, "imagens"),
        KIND_TEXT: (MAX_DOCUMENT_BYTES, "documentos de texto"),
        KIND_SHEET: (MAX_SHEET_BYTES, "planilhas"),
        KIND_MEDIA: (MAX_UPLOAD_BYTES, "vídeo e áudio"),
    }[kind]


def too_big_message(kind: str) -> str:
    limit, label = size_limit(kind)
    megabytes = limit // MIB
    shown = f"{megabytes // 1024} GB" if megabytes >= 1024 else f"{megabytes} MB"
    return f"O arquivo passa do limite de {shown} para {label}."


def require_real_image(upload: UploadFile, name: str) -> None:
    """Recusa o arquivo cujo conteúdo não é a imagem que a extensão diz, antes de gravar qualquer coisa em disco.

    Olhar os primeiros bytes antes de gravar evita deixar o impostor em `cache/uploads`, onde o nome leva o conteúdo e
    outro uso do mesmo arquivo poderia ser apagado junto. Um arquivo vazio passa: quem o recusa, com o motivo certo, é o upload.
    """
    head = upload.file.read(16)
    upload.file.seek(0)
    if head and not image_signature_matches(head, upload_file_name(upload)):
        raise AttachmentRefused(
            f"O arquivo '{name}' não é uma imagem {Path(name).suffix.upper().lstrip('.')} de verdade: "
            "o conteúdo não bate com a extensão."
        )


class AttachmentService:
    """Guarda e entrega os anexos de uma conversa. O disco e o leitor de planilha são dele; a regra de negócio é pura."""

    def __init__(
        self,
        sheet_reader: SheetReader = read_sheet,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:10],
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self._read_sheet = sheet_reader
        self._new_id = new_id
        self._clock = clock

    # ---------- receber ----------

    def ingest(self, conversation: Conversation, upload: UploadFile) -> AttachmentRecord:
        """Recebe um arquivo e o registra na conversa como anexo pendente. Levanta `AttachmentRefused` (422) ou
        `HTTPException` (413, 400) quando o arquivo não serve."""
        name = display_name(upload)
        kind = classify(name)
        if kind == KIND_MEDIA and conversation.record.mode == MODE_FREE:
            raise AttachmentRefused(
                "Vídeo e áudio só podem ser anexados numa conversa do tipo Operar o DMaker: "
                "a conversa livre não tem ferramentas para abri-los."
            )
        attachment_id = self._new_id()
        folder = conversation.store.attachments_dir(conversation.id)
        receive = {
            KIND_IMAGE: self._receive_image,
            KIND_MEDIA: self._receive_media,
            KIND_SHEET: self._receive_sheet,
            KIND_TEXT: self._receive_text,
        }[kind]
        if kind == KIND_IMAGE and conversation.record.mode == MODE_OPERATE:
            receive = self._receive_working_image
        record = receive(upload, name, attachment_id, folder)
        conversation.add_attachment(record)
        return record

    def _record(self, attachment_id: str, kind: str, name: str, size: int, **fields: Any) -> AttachmentRecord:
        return AttachmentRecord(attachment_id, kind, name, size, self._clock(), **fields)

    def _receive_image(
        self, upload: UploadFile, name: str, attachment_id: str, folder: Path
    ) -> AttachmentRecord:
        require_real_image(upload, name)
        saved = save_upload(
            upload, folder, size_limit(KIND_IMAGE)[0], too_big_message(KIND_IMAGE), attachment_id
        )
        return self._record(attachment_id, KIND_IMAGE, name, saved.size, file=saved.path.name)

    def _receive_working_image(
        self, upload: UploadFile, name: str, attachment_id: str, folder: Path
    ) -> AttachmentRecord:
        """A imagem de uma conversa que opera o DMaker: arquivo de trabalho em `cache/uploads`, como o vídeo."""
        require_real_image(upload, name)
        saved = save_upload(
            upload, media_upload_dir(), size_limit(KIND_IMAGE)[0], too_big_message(KIND_IMAGE)
        )
        return self._record(attachment_id, KIND_IMAGE, name, saved.size, path=saved.path.as_posix())

    def _receive_media(
        self, upload: UploadFile, name: str, attachment_id: str, folder: Path
    ) -> AttachmentRecord:
        saved = save_upload(
            upload, media_upload_dir(), size_limit(KIND_MEDIA)[0], too_big_message(KIND_MEDIA)
        )
        return self._record(attachment_id, KIND_MEDIA, name, saved.size, path=saved.path.as_posix())

    def _receive_sheet(
        self, upload: UploadFile, name: str, attachment_id: str, folder: Path
    ) -> AttachmentRecord:
        saved = save_upload(
            upload, media_upload_dir(), size_limit(KIND_SHEET)[0], too_big_message(KIND_SHEET)
        )
        is_csv = saved.path.suffix.lower() == ".csv"
        try:
            sheet: Sheet | None = self._read_sheet(saved.path)
            problem: Exception | None = None
        except Exception as exc:  # noqa: BLE001 - o openpyxl levanta de tudo diante de um .xlsx quebrado
            sheet, problem = None, exc
        if is_csv and (
            sheet is None or not sheet.headers
        ):  # um .csv sem forma de planilha ainda é texto que se lê
            return self._text_record(saved.path.read_bytes(), name, attachment_id, folder)
        if sheet is None:
            reason = (
                str(problem)
                if isinstance(problem, SheetError)
                else "o arquivo está corrompido ou não é uma planilha"
            )
            raise AttachmentRefused(f"Não consegui ler a planilha '{name}': {reason}") from problem
        return self._record(
            attachment_id,
            KIND_SHEET,
            name,
            saved.size,
            path=saved.path.as_posix(),
            preview=sheet_preview(sheet),
        )

    def _receive_text(
        self, upload: UploadFile, name: str, attachment_id: str, folder: Path
    ) -> AttachmentRecord:
        data = read_upload(upload, size_limit(KIND_TEXT)[0], too_big_message(KIND_TEXT))
        return self._text_record(data, name, attachment_id, folder)

    def _text_record(self, data: bytes, name: str, attachment_id: str, folder: Path) -> AttachmentRecord:
        """Extrai o texto e o guarda na pasta da conversa; `AttachmentRefused` se o arquivo não tem texto."""
        try:
            text = extract_text(data, name, CSV_AS_TEXT)
        except DocumentError as exc:
            raise AttachmentRefused(f"{name}: {exc}") from exc
        text = text[
            :MAX_EXTRACTED_CHARS
        ]  # ao modelo vai uma parte: o orçamento de contexto, na hora de enviar
        folder.mkdir(parents=True, exist_ok=True)
        stored = folder / f"{attachment_id}.txt"
        partial = stored.with_suffix(".txt.part")
        partial.write_text(text, encoding="utf-8")
        partial.replace(stored)
        return self._record(
            attachment_id,
            KIND_TEXT,
            name,
            len(data),
            file=stored.name,
            total_chars=len(text),
            preview={"excerpt": text[:EXCERPT_CHARS]},
        )

    # ---------- esquecer ----------

    def discard(self, conversation: Conversation, attachment_id: str) -> None:
        """Esquece um anexo que ainda não foi enviado e apaga o que ficou na pasta da conversa.

        O que foi para `cache/uploads` só é esquecido: o arquivo pode estar em uso por um projeto ou por outro anexo.
        """
        attachment = conversation.attachment(attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Anexo desconhecido nesta conversa.")
        if attachment.sent:
            raise HTTPException(
                status_code=409,
                detail="Este anexo já foi enviado numa mensagem e fica na conversa; não dá para removê-lo.",
            )
        conversation.remove_attachment(attachment_id)
        stored = conversation.attachment_path(attachment)
        if stored is not None:
            try:
                stored.unlink(missing_ok=True)
            except OSError:
                pass  # arquivo em uso: fica na pasta e vai embora junto com a conversa

    # ---------- enviar ----------

    def lookup(self, conversation: Conversation, attachment_ids: Sequence[str]) -> list[AttachmentRecord]:
        """Os registros dos ids de uma mensagem, na ordem, sem repetir. 422 para id desconhecido ou demais anexos."""
        unique = list(dict.fromkeys(attachment_ids))
        if len(unique) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise HTTPException(
                status_code=422, detail=f"Uma mensagem leva no máximo {MAX_ATTACHMENTS_PER_MESSAGE} anexos."
            )
        records: list[AttachmentRecord] = []
        for attachment_id in unique:
            record = conversation.attachment(attachment_id)
            if record is None:
                raise HTTPException(
                    status_code=422, detail=f"Anexo desconhecido nesta conversa: {attachment_id}."
                )
            records.append(record)
        return records

    def load(
        self, conversation: Conversation, records: Sequence[AttachmentRecord], can_use_files: bool
    ) -> list[AttachedFile]:
        """Os anexos prontos para a mensagem: confere que ninguém foi enviado antes, que os arquivos ainda existem
        e que a conversa pode usá-los, e lê o texto extraído."""
        files: list[AttachedFile] = []
        for record in records:
            if record.sent:
                raise HTTPException(
                    status_code=409,
                    detail=f"O anexo '{record.name}' já foi enviado em outra mensagem. Anexe de novo para usá-lo outra vez.",
                )
            if record.kind == KIND_MEDIA and not can_use_files:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"'{record.name}' é vídeo ou áudio, e a conversa livre não tem ferramentas para abri-lo. "
                        "Remova o anexo ou use uma conversa do tipo Operar o DMaker."
                    ),
                )
            if record.kind == KIND_IMAGE and can_use_files:
                self._ensure_working_file(conversation, record)
            files.append(AttachedFile(record, self._read_stored_text(conversation, record)))
        return files

    def _ensure_working_file(self, conversation: Conversation, record: AttachmentRecord) -> None:
        """Garante a cópia de trabalho de uma imagem que vai a uma conversa que opera o DMaker.

        A imagem anexada antes de o modo mudar (ou antes de a imagem virar arquivo de trabalho) só existe na pasta da
        conversa; as ferramentas leem por caminho, então ela ganha em `cache/uploads` o mesmo arquivo que um upload
        de Operar teria, pelo mesmo conteúdo no nome (a mesma foto reaproveita o caminho).
        """
        if record.path and Path(record.path).is_file():
            return
        source = conversation.attachment_path(record)
        if source is None or not source.is_file():
            return  # sem arquivo de origem: `_read_stored_text` diz que sumiu e pede para anexar de novo
        try:
            with source.open("rb") as handle:
                saved = save_upload(
                    UploadFile(handle, filename=record.name),
                    media_upload_dir(),
                    size_limit(KIND_IMAGE)[0],
                    too_big_message(KIND_IMAGE),
                )
        except OSError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Não consegui preparar a imagem '{record.name}' para o editor usar. Anexe-a de novo.",
            ) from exc
        conversation.bind_working_file(record.id, saved.path.as_posix())

    def _read_stored_text(self, conversation: Conversation, record: AttachmentRecord) -> str:
        stored = conversation.attachment_file(record)
        if stored is None or not stored.is_file():
            raise HTTPException(
                status_code=422,
                detail=f"O arquivo de '{record.name}' não está mais disponível. Anexe-o de novo.",
            )
        if record.kind != KIND_TEXT:
            return ""
        try:
            return stored.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Não consegui reler o texto de '{record.name}'. Anexe-o de novo."
            ) from exc


def register_attachment_routes(
    router: APIRouter,
    service: AttachmentService,
    open_conversation: OpenConversation,
    settings: Callable[[], AgentSettings],
) -> None:
    """As rotas de anexo, penduradas no roteador do agente: enviar, listar a imagem e remover antes de enviar."""

    base = "/api/agent/conversations/{conversation_id}/attachments"

    @router.post(base)
    def upload_attachment(conversation_id: str, file: Annotated[UploadFile, File()]) -> dict:
        current = settings()
        conversation = open_conversation(conversation_id, current)
        try:
            record = service.ingest(conversation, file)
        except AttachmentRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return record.public(settings_for_conversation(current, conversation.record).num_ctx)

    @router.get(base + "/{attachment_id}")
    def attachment_image(conversation_id: str, attachment_id: str) -> FileResponse:
        """A imagem de um anexo, com o tipo certo, para a miniatura. O id é conferido contra a conversa."""
        conversation = open_conversation(conversation_id, settings())
        record = conversation.attachment(attachment_id)
        path = conversation.attachment_file(record) if record is not None else None
        if record is None or record.kind != KIND_IMAGE or path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Este anexo não tem uma imagem para mostrar.")
        return FileResponse(
            path,
            media_type=image_mime(path.name),
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
        )

    @router.delete(base + "/{attachment_id}")
    def delete_attachment(conversation_id: str, attachment_id: str) -> dict:
        service.discard(open_conversation(conversation_id, settings()), attachment_id)
        return {"deleted": attachment_id}
