"""Add risk engine tables — portfolio snapshots, circuit breakers, kill switch, compliance log.

Revision ID: 003
Revises: 002
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # portfolio_snapshots — periodic NAV / P&L snapshots for drawdown tracking
    # ------------------------------------------------------------------
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("portfolio_value", sa.Numeric, nullable=False),
        sa.Column("cash", sa.Numeric),
        sa.Column("invested", sa.Numeric),
        sa.Column("unrealized_pnl", sa.Numeric),
        sa.Column("realized_pnl", sa.Numeric),
        sa.Column("day_start_value", sa.Numeric),
        sa.Column("week_start_value", sa.Numeric),
        sa.Column("month_start_value", sa.Numeric),
        sa.Column("peak_value", sa.Numeric),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_portfolio_snapshots_snapshot_at",
        "portfolio_snapshots",
        ["snapshot_at"],
    )

    # ------------------------------------------------------------------
    # circuit_breaker_events — audit log for breaker triggers and resets
    # ------------------------------------------------------------------
    op.create_table(
        "circuit_breaker_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("breaker_level", sa.String(50), nullable=False),
        sa.Column("threshold_pct", sa.Numeric, nullable=False),
        sa.Column("drawdown_pct", sa.Numeric, nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("reset_at", sa.DateTime(timezone=True)),
        sa.Column("reset_by", sa.String(100)),
    )

    op.create_index(
        "ix_circuit_breaker_events_triggered_at",
        "circuit_breaker_events",
        ["triggered_at"],
    )

    # ------------------------------------------------------------------
    # kill_switch_state — persistent kill switch state across restarts
    # ------------------------------------------------------------------
    op.create_table(
        "kill_switch_state",
        sa.Column("level", sa.String(20), primary_key=True),
        sa.Column("active", sa.Boolean, server_default="false", nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True)),
        sa.Column("triggered_by", sa.String(100)),
        sa.Column("reason", sa.Text),
    )

    # Pre-populate the three kill switch levels (all inactive)
    op.execute(
        """
        INSERT INTO kill_switch_state (level, active)
        VALUES ('strategy', false), ('account', false), ('system', false)
        """
    )

    # ------------------------------------------------------------------
    # compliance_log — regulatory compliance check results
    # ------------------------------------------------------------------
    op.create_table(
        "compliance_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("rule", sa.String(50), nullable=False),
        sa.Column(
            "ticker_id",
            sa.Integer,
            sa.ForeignKey("tickers.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "order_id",
            sa.Integer,
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("violation_type", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("blocking", sa.Boolean, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_compliance_log_ticker_created",
        "compliance_log",
        ["ticker_id", "created_at"],
    )

    op.create_index(
        "ix_compliance_log_rule",
        "compliance_log",
        ["rule"],
    )


def downgrade() -> None:
    op.drop_table("compliance_log")
    op.drop_table("kill_switch_state")
    op.drop_table("circuit_breaker_events")
    op.drop_table("portfolio_snapshots")
