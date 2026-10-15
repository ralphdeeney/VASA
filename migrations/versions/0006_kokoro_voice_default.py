"""Move the retired default voice to Kokoro Maple.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE agents SET voice = 'kokoro_af_maple' WHERE voice = 'ljspeech_en'"))
    op.alter_column("agents", "voice", server_default="kokoro_af_maple")


def downgrade() -> None:
    op.execute(sa.text("UPDATE agents SET voice = 'ljspeech_en' WHERE voice = 'kokoro_af_maple'"))
    op.alter_column("agents", "voice", server_default="ljspeech_en")
