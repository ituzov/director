"""Справки instagram для соседей: frozen dataclass, а не записи из базы."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class AccountRef:
    """Подключённый аккаунт Instagram для соседей: без токена."""

    id: uuid.UUID
    ig_user_id: str
    username: str
    # active, token_expired, disconnected
    status: str


@dataclass(frozen=True, slots=True)
class CommentRef:
    """Коммент под постом, разобранный из входящих."""

    # наш аккаунт, под чьим постом написали
    account_id: uuid.UUID
    # на него отвечают Private Reply
    comment_id: str
    # пост
    media_id: str
    # автор; тот же id, что у него в директе
    person_id: str
    username: str | None
    text: str
    # когда Meta прислала вебхук: время коммента для журнала
    received_at: datetime
    # коммент написан ответом на этот; None: коммент под самим постом
    parent_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommentTextRef:
    """Что видно о комменте во входящих: ник автора и текст. None: Meta не прислала."""

    username: str | None
    text: str | None


@dataclass(frozen=True, slots=True)
class PostbackRef:
    """Нажатие кнопки в директе, разобранное из входящих."""

    # наш аккаунт, в чьём директе нажали
    account_id: uuid.UUID
    # кто нажал; тот же id, что автор коммента
    person_id: str
    # то, что мы положили в кнопку, как есть
    payload: str
    # id нажатия у Meta: по нему одно нажатие не обработать дважды
    mid: str
    # когда нажали по часам Meta; по ним меряем двойной тап
    acted_at: datetime
    # когда вебхук пришёл к нам, по нашим часам: на них же время отправок,
    # и шаги одной истории не перепутаются, если часы Meta убежали
    received_at: datetime


@dataclass(frozen=True, slots=True)
class Button:
    """Кнопка под сообщением. payload Meta вернёт вебхуком нажатия как есть."""

    title: str
    payload: str


@dataclass(frozen=True, slots=True)
class OutboxResult:
    """Чем кончилась отправка исходящего. Уходит тому, кто его поставил, по ref."""

    ref: str
    # private_reply, message, comment_reply
    kind: str
    # sent, failed, expired
    outcome: str
    # код ошибки Meta или наша причина; None у sent
    reason: str | None
    # когда отправка закончилась. Отчёт может опоздать (упал, повтор через
    # 30 секунд и позже): время события берут отсюда, а не из часов отчёта
    finished_at: datetime
    # у отправки с проверкой подписки: following, not_following или unknown
    # (проверить не дали, ушёл вариант, который вызывающий выбрал на этот случай)
    variant: str | None = None


@dataclass(frozen=True, slots=True)
class Handled:
    """Кто взял входящее событие себе. by: модуль, имя даёт worker. ref: что именно
    у него, строка, которую понимает только он (id автоответа, диалога); None, если
    не определить. instagram только хранит пару и отдаёт её ленте."""

    by: str
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class InboxHandlers:
    """Кому отдать разобранное из входящих. Собирает worker, порядок
    «сначала автоответы, потом ассистент» тоже его. None: этот вид пока
    никому не нужен, событие просто отмечается разобранным.
    Обработчик возвращает Handled, если событие взяли, или None: не взял никто."""

    on_comment: Callable[[AsyncSession, CommentRef], Awaitable[Handled | None]] | None = None
    on_postback: Callable[[AsyncSession, PostbackRef], Awaitable[Handled | None]] | None = None
