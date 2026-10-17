"""Timeweb AI Gateway: OpenAI-формат, оплата в рублях, модели многих провайдеров
по одному ключу (Claude как anthropic/claude-haiku-5-5)."""

from typing import Any

from app.ai.providers.openai_compatible import OpenAICompatible

# у части моделей Timeweb нет поля mode, среди них и текстовые (YandexGPT), и
# эмбеддинги, картинки, видео. Без mode отсекаем то, что явно не текст: лишнее
# в списке видно сразу, а пропавшая нужная модель незаметна
_NOT_TEXT_PREFIXES = ("runway/", "black_forest_labs/")
_NOT_TEXT_PARTS = ("embed", "bge")


class TimewebProvider(OpenAICompatible):
    kind = "timeweb"
    default_url = "https://api.timeweb.ai/v1"

    def keep(self, raw: dict[str, Any]) -> bool:
        mode = raw.get("mode")
        if mode is not None:
            # responses, realtime и прочие режимы не говорят через chat/completions
            return mode == "chat"
        model_id = str(raw["id"])
        return not model_id.startswith(_NOT_TEXT_PREFIXES) and not any(
            part in model_id for part in _NOT_TEXT_PARTS
        )
