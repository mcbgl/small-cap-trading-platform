"""Initial schema — core tables for tickers, signals, orders, positions, audit log.

Revision ID: 001
Revises:
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tickers
    # ------------------------------------------------------------------
    op.create_table(
        "tickers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(100)),
        sa.Column("industry", sa.String(100)),
        sa.Column("market_cap", sa.Numeric),
        sa.Column("avg_volume", sa.BigInteger),
        sa.Column("exchange", sa.String(20)),
        sa.Column("is_otc", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    # ------------------------------------------------------------------
    # watchlists
    # ------------------------------------------------------------------
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ------------------------------------------------------------------
    # watchlist_items
    # ------------------------------------------------------------------
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "watchlist_id",
            sa.Integer,
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("watchlist_id", "ticker_id", name="uq_watchlist_ticker"),
    )

    # ------------------------------------------------------------------
    # signals
    # ------------------------------------------------------------------
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("score", sa.Numeric(4, 2)),
        sa.Column("confidence", sa.Numeric(3, 2)),
        sa.Column("model", sa.String(100)),
        sa.Column("reasoning", sa.Text),
        sa.Column("raw_output", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("ix_signals_ticker_created", "signals", ["ticker_id", "created_at"])
    op.create_index("ix_signals_signal_type", "signals", ["signal_type"])

    # ------------------------------------------------------------------
    # orders
    # ------------------------------------------------------------------
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="SET NULL"),
        ),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Numeric, nullable=False),
        sa.Column("price", sa.Numeric),
        sa.Column("order_type", sa.String(20), server_default="limit"),
        sa.Column("status", sa.String(20), server_default="created"),
        sa.Column("stop_loss", sa.Numeric),
        sa.Column("broker", sa.String(50)),
        sa.Column("broker_order_id", sa.String(100)),
        sa.Column("paper_mode", sa.Boolean, server_default="true"),
        sa.Column("filled_qty", sa.Numeric, server_default="0"),
        sa.Column("filled_avg_price", sa.Numeric),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("filled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
    )

    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_ticker", "orders", ["ticker_id"])

    # ------------------------------------------------------------------
    # positions
    # ------------------------------------------------------------------
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("side", sa.String(5), server_default="long"),
        sa.Column("qty", sa.Numeric, nullable=False),
        sa.Column("avg_entry_price", sa.Numeric, nullable=False),
        sa.Column("current_price", sa.Numeric),
        sa.Column("unrealized_pnl", sa.Numeric),
        sa.Column("stop_loss", sa.Numeric, nullable=False),
        sa.Column("trailing_stop_pct", sa.Numeric),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    # ------------------------------------------------------------------
    # audit_log
    # ------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(100)),
        sa.Column("prompt_hash", sa.String(64)),
        sa.Column("input_snapshot", JSONB),
        sa.Column("output", JSONB),
        sa.Column("decision", sa.String(50)),
        sa.Column("human_override", sa.Boolean, server_default="false"),
        sa.Column(
            "order_id",
            sa.Integer,
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_model", "audit_log", ["model_id"])

    # ------------------------------------------------------------------
    # system_config
    # ------------------------------------------------------------------
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("system_config")
    op.drop_table("audit_log")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_table("tickers")
