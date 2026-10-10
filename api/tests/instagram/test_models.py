"""Модель MetaApp: строка ровно одна, это держит база, а не только код."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.instagram.models import MetaApp


def make_app(**kw) -> MetaApp:
    return MetaApp(app_id="1", app_secret_encrypted="x", verify_token="t", **kw)


async def test_second_row_rejected(session):
    session.add(make_app())
    await session.commit()

    # с id = 1 не пустит первичный ключ, а с любым другим проверка single_row
    session.add(make_app(id=2))
    with pytest.raises(IntegrityError, match="ck_meta_app_single_row"):
        await session.commit()
