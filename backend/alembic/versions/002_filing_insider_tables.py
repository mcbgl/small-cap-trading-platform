"""Add filings and insider_transactions tables for SEC EDGAR monitoring.

Revision ID: 002
Revises: 001
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # filings — SEC EDGAR filing records (8-K, 10-K, 10-Q, SC 13D/G)
    # ------------------------------------------------------------------
    op.create_table(
        "filings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cik", sa.String(20)),
        sa.Column("accession_number", sa.String(30), unique=True, nullable=False),
        sa.Column("form_type", sa.String(20), nullable=False),
        sa.Column("filed_date", sa.Date),
        sa.Column("title", sa.Text),
        sa.Column("url", sa.Text),
        sa.Column("keywords_found", JSONB),
        sa.Column("ai_summary", sa.Text),
        sa.Column("ai_score", sa.Float),
        sa.Column("processed", sa.Boolean, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_index("ix_filings_ticker_filed", "filings", ["ticker_id", "filed_date"])
    op.create_index("ix_filings_form_type", "filings", ["form_type"])
    op.create_index("ix_filings_accession", "filings", ["accession_number"], unique=True)

    # ------------------------------------------------------------------
    # insider_transactions — SEC Form 4 insider trades
    # ------------------------------------------------------------------
    op.create_table(
        "insider_transactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cik", sa.String(20)),
        sa.Column("insider_name", sa.String(255), nullable=False),
        sa.Column("insider_role", sa.String(255)),
        sa.Column("transaction_type", sa.String(5), nullable=False),
        sa.Column("transaction_date", sa.Date, nullable=False),
        sa.Column("shares", sa.Numeric, nullable=False),
        sa.Column("price_per_share", sa.Numeric),
        sa.Column("total_value", sa.Numeric),
        sa.Column("shares_after", sa.Numeric),
        sa.Column("form4_url", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_insider_txn_ticker_date",
        "insider_transactions",
        ["ticker_id", "transaction_date"],
    )
    op.create_index(
        "ix_insider_txn_insider_name",
        "insider_transactions",
        ["insider_name"],
    )


def downgrade() -> None:
    op.drop_table("insider_transactions")
    op.drop_table("filings")
