"""Ассистенты аккаунта: создать, сохранить, пауза, архив. Правила мест как у
автоответов: общий у аккаунта один, пост у одного частного, пауза держит,
архив отпускает."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app import ai, identity, instagram
from app.assistant import prompt, repository
from app.assistant.exceptions import (
    AccountUnavailable,
    AssistantArchived,
    AssistantConflict,
    AssistantNotFound,
    ConnectionMissing,
)
from app.assistant.models import Assistant
from app.assistant.schemas import AssistantForm, AssistantIn, TryIn

log = structlog.get_logger("app.assistant")

# задача в ai: через какое подключение и модель отвечает ассистент (scope = id)
ANSWER = "assistant.answer"
# проверка в песочнице: своя задача, траты на проверки видны отдельно
TRY = "assistant.try"


@dataclass(frozen=True, slots=True)
class Full:
    """Ассистент со всем, что нужно форме и строке списка."""

    assistant: Assistant
    media_ids: list[str]
    # None: настройки нет или подключение удалили
    binding: ai.BindingRef | None
    # итоги прочитанных за сутки UTC: answered, unsure, not_mine…
    today: dict[str, int]


def day_start(now: datetime | None = None) -> datetime:
    """Начало суток UTC: от него счётчики «сегодня» и предел."""
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def create(session: AsyncSession, form: AssistantIn, user: identity.UserRef) -> Full:
    account = await instagram.get_account(session, form.account_id)
    if account is None or account.status == "disconnected":
        raise AccountUnavailable
    await repository.lock_account(session, form.account_id)
    await _check_conflicts(session, form.account_id, form.scope, form.media_ids, exclude_id=None)

    assistant = Assistant(account_id=form.account_id, created_by=user.id, **_fields(form))
    repository.add_assistant(session, assistant)
    await session.flush()
    repository.add_media(session, assistant.id, form.media_ids)
    await _bind(session, assistant.id, form)
    await session.commit()
    log.info("assistant.created", assistant_id=str(assistant.id), account_id=str(form.account_id))
    return await get(session, assistant.id)


async def update(session: AsyncSession, assistant_id: uuid.UUID, form: AssistantForm) -> Full:
    """Сохранить форму целиком: посты заменяются тем, что прислали."""
    assistant = await _locked(session, assistant_id)
    if assistant.archived_at is not None:
        raise AssistantArchived
    await _check_conflicts(
        session, assistant.account_id, form.scope, form.media_ids, exclude_id=assistant.id
    )
    for name, value in _fields(form).items():
        setattr(assistant, name, value)
    assistant.updated_at = func.now()
    await repository.replace_media(session, assistant.id, form.media_ids)
    await _bind(session, assistant.id, form)
    await session.commit()
    log.info("assistant.updated", assistant_id=str(assistant.id))
    return await get(session, assistant.id)


async def set_enabled(session: AsyncSession, assistant_id: uuid.UUID, enabled: bool) -> Full:
    """Пауза и обратно. Конфликтов нет: на паузе и так держит своё место."""
    assistant = await _locked(session, assistant_id)
    if assistant.archived_at is not None:
        raise AssistantArchived
    if assistant.enabled != enabled:
        assistant.enabled = enabled
        assistant.updated_at = func.now()
        await session.commit()
        log.info("assistant.enabled", assistant_id=str(assistant.id), enabled=enabled)
    return await get(session, assistant.id)


async def archive(session: AsyncSession, assistant_id: uuid.UUID) -> Full:
    """В архив: перестаёт отвечать и отпускает посты. Повтор ничего не меняет."""
    assistant = await _locked(session, assistant_id)
    if assistant.archived_at is None:
        assistant.archived_at = func.now()
        await repository.set_media_archived(session, assistant.id, True)
        await session.commit()
        log.info("assistant.archived", assistant_id=str(assistant.id))
    return await get(session, assistant.id)


async def unarchive(session: AsyncSession, assistant_id: uuid.UUID) -> Full:
    """Из архива, если место за это время никто не занял."""
    assistant = await _locked(session, assistant_id)
    if assistant.archived_at is not None:
        media_ids = (await repository.media_by_assistant(session, [assistant.id])).get(
            assistant.id, []
        )
        await _check_conflicts(
            session, assistant.account_id, assistant.scope, media_ids, exclude_id=assistant.id
        )
        assistant.archived_at = None
        await repository.set_media_archived(session, assistant.id, False)
        await session.commit()
        log.info("assistant.unarchived", assistant_id=str(assistant.id))
    return await get(session, assistant.id)


async def get(session: AsyncSession, assistant_id: uuid.UUID) -> Full:
    assistant = await _existing(session, assistant_id)
    # после commit время и флаги считала база: перечитываем строку
    await session.refresh(assistant)
    [full] = await _with_details(session, [assistant])
    return full


async def list_for_account(
    session: AsyncSession, account_id: uuid.UUID, *, archived: bool
) -> list[Full]:
    return await _with_details(
        session, await repository.list_assistants(session, account_id, archived=archived)
    )


async def _with_details(session: AsyncSession, assistants: list[Assistant]) -> list[Full]:
    ids = [a.id for a in assistants]
    media = await repository.media_by_assistant(session, ids)
    bindings = await ai.bindings(session, purpose=ANSWER, scopes=[str(i) for i in ids])
    today = await repository.outcomes_since(session, ids, day_start())
    return [
        Full(a, media.get(a.id, []), bindings.get(str(a.id)), today.get(a.id, {}))
        for a in assistants
    ]


async def _existing(session: AsyncSession, assistant_id: uuid.UUID) -> Assistant:
    assistant = await repository.get_assistant(session, assistant_id)
    if assistant is None:
        raise AssistantNotFound
    return assistant


async def _locked(session: AsyncSession, assistant_id: uuid.UUID) -> Assistant:
    """Ассистент для изменения: под замком аккаунта и перечитанный после него.
    Иначе архив, успевший между чтением и записью формы, получил бы обратно живые
    посты: форма заменяет их строками с archived = false."""
    account_id = (await _existing(session, assistant_id)).account_id
    await repository.lock_account(session, account_id)
    assistant = await repository.lock_assistant(session, assistant_id)
    if assistant is None:
        raise AssistantNotFound
    return assistant


async def _bind(session: AsyncSession, assistant_id: uuid.UUID, form: AssistantForm) -> None:
    """Подключение и модель в ai, в этой же транзакции: форма и модель
    сохраняются вместе или никак."""
    try:
        await ai.set_binding(
            session,
            purpose=ANSWER,
            scope=str(assistant_id),
            connection_id=form.connection_id,
            model=form.model,
        )
    except ai.ConnectionNotFound:
        raise ConnectionMissing from None


async def _check_conflicts(
    session: AsyncSession,
    account_id: uuid.UUID,
    scope: str,
    media_ids: list[str],
    *,
    exclude_id: uuid.UUID | None,
) -> None:
    """Общий у аккаунта один, частные не делят посты. Архивные никому не мешают,
    на паузе мешают: включат обратно, и конфликт всплывёт молча."""
    if scope == "all":
        other = await repository.live_general(session, account_id, exclude_id)
        if other is not None:
            raise AssistantConflict(
                "general",
                value=None,
                assistant_id=other.id,
                name=other.name,
                enabled=other.enabled,
            )
        return
    taken = await repository.taken_media(session, media_ids, exclude_id)
    if taken is not None:
        media_id, other = taken
        raise AssistantConflict(
            "post", value=media_id, assistant_id=other.id, name=other.name, enabled=other.enabled
        )


def _fields(form: AssistantForm) -> dict:
    """Поля самой строки: без постов (своя таблица) и модели (она в ai)."""
    return form.model_dump(exclude={"media_ids", "account_id", "connection_id", "model"})


async def try_answer(body: TryIn) -> tuple[prompt.Decision | None, str | None]:
    """Как ответил бы ассистент с этими полями: решение или код ошибки ai.
    Без сессии вызывающего: ai.run берёт свои короткие, пока модель думает,
    транзакция не открыта."""
    brief = prompt.Brief(body.mode, body.instruction, body.knowledge)
    try:
        result = await ai.run(
            purpose=TRY,
            scope=str(body.assistant_id) if body.assistant_id else None,
            agent=prompt.agent(brief),
            prompt=prompt.comment_prompt(body.comment),
            using=ai.Using(body.connection_id, body.model),
        )
    except ai.AiCallFailed as error:
        log.info("assistant.try_failed", code=error.code)
        return None, error.code
    return result.output, None
