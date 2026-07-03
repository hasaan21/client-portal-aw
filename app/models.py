"""SQLAlchemy ORM models — every persistent entity for the AW Client Portal.

Design notes:
- `Decimal` (SQL `NUMERIC(14, 2)`) for money. Never float.
- Retirement accounts must be owned by CLIENT1 or CLIENT2 (never JOINT). Enforced in the
  Account.__init__ layer and re-checked at report-generation time.
- Every finalized report snapshots its balances so editing a client's profile later
  cannot mutate historical numbers.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

_hasher = PasswordHasher()


class ReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class AccountSection(str, enum.Enum):
    """Where an account appears in the reports."""

    SACS_INFLOW = "SACS_INFLOW"
    SACS_OUTFLOW = "SACS_OUTFLOW"
    SACS_PRIVATE_RESERVE = "SACS_PRIVATE_RESERVE"
    SACS_INVESTMENT = "SACS_INVESTMENT"
    RETIREMENT = "RETIREMENT"
    NON_RETIREMENT = "NON_RETIREMENT"
    TRUST = "TRUST"


class AccountOwner(str, enum.Enum):
    CLIENT1 = "CLIENT1"
    CLIENT2 = "CLIENT2"
    JOINT = "JOINT"
    TRUST = "TRUST"


class AccountKind(str, enum.Enum):
    IRA = "IRA"
    ROTH_IRA = "ROTH_IRA"
    _401K = "401K"
    PENSION = "PENSION"
    BROKERAGE = "BROKERAGE"
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    HYSA = "HYSA"
    STOCK_OPTIONS = "STOCK_OPTIONS"
    OTHER = "OTHER"


class LiabilityKind(str, enum.Enum):
    MORTGAGE = "MORTGAGE"
    AUTO = "AUTO"
    HEALTH = "HEALTH"
    OTHER = "OTHER"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    reports: Mapped[list[Report]] = relationship(back_populates="created_by")
    audit_entries: Mapped[list[AuditLog]] = relationship(back_populates="user")

    def set_password(self, plaintext: str) -> None:
        self.password_hash = _hasher.hash(plaintext)

    def check_password(self, plaintext: str) -> bool:
        try:
            _hasher.verify(self.password_hash, plaintext)
        except VerifyMismatchError:
            return False
        if _hasher.check_needs_rehash(self.password_hash):
            self.password_hash = _hasher.hash(plaintext)
        return True

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Client(TimestampMixin, db.Model):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    household_label: Mapped[str] = mapped_column(String(120), nullable=False)

    # Client 1 (required)
    c1_first: Mapped[str] = mapped_column(String(80), nullable=False)
    c1_last: Mapped[str] = mapped_column(String(80), nullable=False)
    c1_dob: Mapped[date] = mapped_column(Date, nullable=False)
    c1_ssn_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    c1_monthly_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Client 2 (optional / married households)
    c2_first: Mapped[str | None] = mapped_column(String(80))
    c2_last: Mapped[str | None] = mapped_column(String(80))
    c2_dob: Mapped[date | None] = mapped_column(Date)
    c2_ssn_last4: Mapped[str | None] = mapped_column(String(4))
    c2_monthly_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    monthly_expense_budget: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    private_reserve_target_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    private_reserve_label: Mapped[str] = mapped_column(
        String(60), nullable=False, default="PRIVATE RESERVE"
    )
    trust_label: Mapped[str] = mapped_column(String(120), nullable=False, default="Family Trust")
    trust_property_address: Mapped[str | None] = mapped_column(String(255))

    accounts: Mapped[list[Account]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        order_by="Account.order_idx",
    )
    liabilities: Mapped[list[Liability]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        order_by="Liability.order_idx",
    )
    deductibles: Mapped[list[InsuranceDeductible]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        order_by="Report.meeting_date.desc()",
    )

    __table_args__ = (
        CheckConstraint("length(c1_ssn_last4) = 4", name="ck_clients_c1_ssn_4digits"),
        CheckConstraint(
            "c2_ssn_last4 IS NULL OR length(c2_ssn_last4) = 4",
            name="ck_clients_c2_ssn_4digits",
        ),
    )

    @property
    def is_married(self) -> bool:
        return bool(self.c2_first)

    @property
    def display_name(self) -> str:
        return self.household_label or f"{self.c1_first} {self.c1_last}"

    @staticmethod
    def _age_from(dob: date | None) -> int | None:
        if dob is None:
            return None
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @property
    def c1_age(self) -> int | None:
        return self._age_from(self.c1_dob)

    @property
    def c2_age(self) -> int | None:
        return self._age_from(self.c2_dob)

    def last_report(self) -> Report | None:
        return self.reports[0] if self.reports else None

    def owner_display(self, owner: AccountOwner) -> str:
        """Resolve an AccountOwner enum to the user-facing label for THIS household.

        CLIENT1/CLIENT2 return the person's first name so dropdowns and tables
        read as e.g. "Andrew" / "Whitney" instead of the generic "Client1".
        JOINT / TRUST stay literal — they're roles, not people.
        """
        if owner == AccountOwner.CLIENT1:
            return self.c1_first or "Client 1"
        if owner == AccountOwner.CLIENT2:
            return self.c2_first or "Client 2"
        if owner == AccountOwner.JOINT:
            return "Joint"
        if owner == AccountOwner.TRUST:
            return "Trust"
        return str(owner.value).title()

    def __repr__(self) -> str:
        return f"<Client {self.household_label}>"


class InsuranceDeductible(db.Model):
    __tablename__ = "insurance_deductibles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    client: Mapped[Client] = relationship(back_populates="deductibles")


class Account(db.Model):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    section: Mapped[AccountSection] = mapped_column(
        Enum(AccountSection, name="account_section"), nullable=False
    )
    owner: Mapped[AccountOwner] = mapped_column(
        Enum(AccountOwner, name="account_owner"), nullable=False
    )
    kind: Mapped[AccountKind] = mapped_column(
        Enum(AccountKind, name="account_kind"), nullable=False
    )
    custodian: Mapped[str | None] = mapped_column(String(80))
    display_name: Mapped[str | None] = mapped_column(String(120))
    last4: Mapped[str | None] = mapped_column(String(4))
    order_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    client: Mapped[Client] = relationship(back_populates="accounts")
    balances: Mapped[list[Balance]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            # Retirement accounts cannot be JOINT — must be CLIENT1 or CLIENT2.
            "(section != 'RETIREMENT') OR (owner IN ('CLIENT1', 'CLIENT2'))",
            name="ck_accounts_retirement_never_joint",
        ),
        CheckConstraint(
            "last4 IS NULL OR length(last4) = 4",
            name="ck_accounts_last4_4digits",
        ),
        Index("ix_accounts_client_section", "client_id", "section"),
    )

    @property
    def label(self) -> str:
        return self.display_name or self.kind.value.replace("_", " ")

    @property
    def owner_label(self) -> str:
        """User-facing owner name (resolves CLIENT1/2 to first names)."""
        return self.client.owner_display(self.owner)


class Liability(db.Model):
    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[LiabilityKind] = mapped_column(
        Enum(LiabilityKind, name="liability_kind"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))  # e.g. 6.125%
    order_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    client: Mapped[Client] = relationship(back_populates="liabilities")
    balances: Mapped[list[LiabilityBalance]] = relationship(
        back_populates="liability", cascade="all, delete-orphan"
    )


class Report(TimestampMixin, db.Model):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"),
        nullable=False,
        default=ReportStatus.DRAFT,
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    sacs_pdf_path: Mapped[str | None] = mapped_column(String(500))
    tcc_pdf_path: Mapped[str | None] = mapped_column(String(500))

    client: Mapped[Client] = relationship(back_populates="reports")
    created_by: Mapped[User] = relationship(back_populates="reports")
    balances: Mapped[list[Balance]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    liability_balances: Mapped[list[LiabilityBalance]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("client_id", "meeting_date", name="uq_reports_client_meeting"),
    )

    @property
    def is_final(self) -> bool:
        return self.status == ReportStatus.FINAL


class Balance(db.Model):
    __tablename__ = "balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    cash_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    as_of_date: Mapped[date | None] = mapped_column(Date)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    report: Mapped[Report] = relationship(back_populates="balances")
    account: Mapped[Account] = relationship(back_populates="balances")

    __table_args__ = (
        UniqueConstraint("report_id", "account_id", name="uq_balance_report_account"),
    )


class LiabilityBalance(db.Model):
    __tablename__ = "liability_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    liability_id: Mapped[int] = mapped_column(
        ForeignKey("liabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    as_of_date: Mapped[date | None] = mapped_column(Date)

    report: Mapped[Report] = relationship(back_populates="liability_balances")
    liability: Mapped[Liability] = relationship(back_populates="balances")

    __table_args__ = (
        UniqueConstraint("report_id", "liability_id", name="uq_liab_balance_report_liab"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    entity: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    diff_json: Mapped[dict[str, Any] | None] = mapped_column(db.JSON)

    user: Mapped[User | None] = relationship(back_populates="audit_entries")

    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)
