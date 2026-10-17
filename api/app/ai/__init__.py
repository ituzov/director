"""ИИ: ключи провайдеров моделей, какая задача через что идёт, журнал вызовов.

Ниже ассистента и автоответов: держит внешнее подключение, как instagram держит
Meta. Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.ai.calls import BAD_OUTPUT, NOT_CONFIGURED, STEP_LIMIT, Using, run
from app.ai.contracts import BindingRef
from app.ai.exceptions import AiCallFailed, AiError, ConnectionNotFound, ModelRequired
from app.ai.routes import ai_error_handler, router
from app.ai.service import bindings, set_binding

__all__ = [
    # вызов модели для задачи: вне своей транзакции, ответа нет значит AiCallFailed
    "run",
    # подключение и модель явно, мимо настройки задачи: для песочницы
    "Using",
    "AiCallFailed",
    "AiError",
    # коды AiCallFailed сверх кодов провайдера
    "NOT_CONFIGURED",
    "STEP_LIMIT",
    "BAD_OUTPUT",
    # через какое подключение и модель идёт задача: в транзакции вызывающего
    "set_binding",
    "bindings",
    "BindingRef",
    # ошибки set_binding: подключения нет, модель не выбрана
    "ConnectionNotFound",
    "ModelRequired",
    # HTTP: экран «Настройки → ИИ»
    "router",
    "ai_error_handler",
]
