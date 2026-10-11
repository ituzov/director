"""activity: autoreply_id вместо campaign_id

Revision ID: 9c169849f072
Revises: f2021d155299
Create Date: 2026-10-11 18:55:38.201284

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c169849f072"
down_revision: Union[str, Sequence[str], None] = "f2021d155299"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # кампании стали автоответами; переименование не трогает данные
    op.alter_column("event", "campaign_id", new_column_name="autoreply_id", schema="activity")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("event", "autoreply_id", new_column_name="campaign_id", schema="activity")
