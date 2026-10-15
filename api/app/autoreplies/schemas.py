"""Схемы HTTP: что ручки autoreplies принимают и отдают. Модели наружу не отдаём.

Форму проверяем здесь целиком, до базы: ошибка формы уходит 422 с кодом в msg
(например keyword_duplicate), по нему web подсвечивает поле.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from app.autoreplies.matching import normalize

# лимит Meta на текст сообщения: 1000 байт, для кириллицы около 500 знаков
MESSAGE_BYTES = 1000


def _fits_message(text: str) -> str:
    if len(text.encode()) > MESSAGE_BYTES:
        raise ValueError("message_too_long")
    return text


def _text(max_length: int | None = None):
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


Name = Annotated[str, _text(100)]
Word = Annotated[str, _text(100)]
MediaId = Annotated[str, _text(100)]
MessageText = Annotated[str, _text(), AfterValidator(_fits_message)]
# сообщение с кнопкой (button template) у Meta до 640 знаков, не байт
ButtonMessageText = Annotated[str, _text(640)]
# лимит кнопки дока Instagram не называет: 20 знаков как в Messenger, с запасом
ButtonText = Annotated[str, _text(20)]
# лимит коммента в Instagram
CommentReply = Annotated[str, _text(2200)]


class AutoreplyForm(BaseModel):
    """Форма автоответа: всё, что владелец может поменять."""

    name: Name
    scope: Literal["all", "posts"]
    # столько форма показывает выбранными: ручка постов по id берёт до 50
    media_ids: list[MediaId] = Field(default=[], max_length=50)
    keywords: list[Word] = Field(min_length=1, max_length=50)
    # уходят с кнопкой
    intro_text: ButtonMessageText
    button_text: ButtonText
    # материал, обычным сообщением
    reply_text: MessageText
    follow_gate: bool = False
    not_following_text: ButtonMessageText | None = None
    comment_replies: list[CommentReply] = Field(default=[], max_length=10)
    # random: любой, кроме прошлого; sequence: по кругу
    comment_reply_mode: Literal["random", "sequence"] = "random"
    enabled: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        normalized = [normalize(word) for word in self.keywords]
        if not all(normalized):
            # одни эмодзи или знаки: искать в комменте нечего
            raise ValueError("keyword_empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("keyword_duplicate")
        if self.scope == "posts" and not self.media_ids:
            raise ValueError("posts_required")
        if self.scope == "all" and self.media_ids:
            raise ValueError("posts_not_allowed")
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("post_duplicate")
        if self.follow_gate and not self.not_following_text:
            raise ValueError("not_following_text_required")
        return self


class AutoreplyIn(AutoreplyForm):
    """Создание: аккаунт задаётся один раз и потом не меняется."""

    account_id: uuid.UUID


class EnabledIn(BaseModel):
    """Переключатель в списке: только вкл/выкл, без всей формы."""

    enabled: bool


class AutoreplyOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    name: str
    scope: str
    media_ids: list[str]
    # как ввёл владелец, в порядке ввода
    keywords: list[str]
    intro_text: str
    button_text: str
    reply_text: str
    follow_gate: bool
    not_following_text: str | None
    comment_replies: list[str]
    comment_reply_mode: str
    enabled: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AutoreplyCountsOut(BaseModel):
    id: uuid.UUID
    name: str
    triggered: int
    delivered: int
    # последнее срабатывание
    last_at: datetime


class StatsOut(BaseModel):
    """Сводка аккаунта за период: воронка выдач, топ и цифры по каждому автоответу."""

    # сработало, ушёл директ с кнопкой, нажали кнопку, получили материал
    triggered: int
    sent: int
    clicked: int
    delivered: int
    # отправки, которые так и не ушли: упали после повторов или опоздали к окну Meta
    undelivered: int
    # чаще всего срабатывавшие, до пяти: для обзора
    top: list[AutoreplyCountsOut]
    # все срабатывавшие за период: для карточек. Кого нет, тот не срабатывал
    by_autoreply: list[AutoreplyCountsOut]


class StepOut(BaseModel):
    """Шаг выдачи: код для текста в web и подробности, если они есть."""

    step: str
    at: datetime
    autoreply_id: uuid.UUID | None
    keyword: str | None
    outcome: str | None
    reason: str | None
    follow: str | None


class HistoryOut(BaseModel):
    """Шаги выдачи по комментам. Коммента без шагов в ответе нет: автоответ его не брал."""

    comments: dict[str, list[StepOut]]


Stage = Literal[
    "sending",
    "waiting_click",
    "dm_failed",
    "clicked",
    "follow_asked",
    "material_failed",
    "delivered",
]


class DeliveryOut(BaseModel):
    id: uuid.UUID
    comment_id: str
    person_id: str
    # ник и текст коммента; None: во входящих его уже нет
    username: str | None
    text: str | None
    autoreply_id: uuid.UUID
    autoreply_name: str
    keyword: str
    stage: Stage
    # с какого момента выдача на этом этапе
    stage_at: datetime
    created_at: datetime


class DeliveryPageOut(BaseModel):
    items: list[DeliveryOut]
    # закладка для следующей страницы, в before; None: дальше пусто
    next: uuid.UUID | None


class StageCountsOut(BaseModel):
    """Сколько выдач сейчас на каждом этапе: для вкладок «Выдач»."""

    counts: dict[Stage, int]
