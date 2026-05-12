"""add doctor_name to patient model

Revision ID: 1b4088099dac
Revises: 625785d8d616
Create Date: 2026-05-12 04:59:37.761308

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1b4088099dac'
down_revision: Union[str, None] = '625785d8d616'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add doctor_name column to existing patient table
    op.add_column('patient', sa.Column('doctor_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    op.drop_column('patient', 'doctor_name')
