"""add appsheet_test_type and appsheet_test_type_code to patient

Revision ID: 2a7b8c9d0e1f
Revises: 1b4088099dac
Create Date: 2026-05-12 05:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2a7b8c9d0e1f'
down_revision: Union[str, None] = '1b4088099dac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add appsheet_test_type and appsheet_test_type_code columns
    op.add_column('patient', sa.Column('appsheet_test_type', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('patient', sa.Column('appsheet_test_type_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    op.drop_column('patient', 'appsheet_test_type_code')
    op.drop_column('patient', 'appsheet_test_type')
