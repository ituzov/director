"""ИИ: ключи провайдеров моделей, какая задача через что идёт, журнал вызовов.

Ниже ассистента и автоответов: держит внешнее подключение, как instagram держит
Meta. Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.ai.calls import BAD_OUTPUT, NOT_CONFIGURED, STEP_LIMIT, run
from app.ai.exceptions import AiCallFailed, AiError
from app.ai.service import set_binding

__all__ = [
    # вызов модели для задачи: вне своей транзакции, ответа нет значит AiCallFailed
    "run",
    "AiCallFailed",
    "AiError",
    # коды AiCallFailed сверх кодов провайдера
    "NOT_CONFIGURED",
    "STEP_LIMIT",
    "BAD_OUTPUT",
    # через какое подключение и модель идёт задача: в транзакции вызывающего
    "set_binding",
]
