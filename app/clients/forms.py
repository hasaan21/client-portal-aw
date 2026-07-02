"""Forms for client CRUD."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    HiddenField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)

from app.models import AccountKind, AccountOwner, AccountSection, LiabilityKind

SSN_LAST4 = Regexp(r"^\d{4}$", message="Enter the last 4 digits (numbers only).")
LAST4_ACCT = Regexp(r"^\d{4}$", message="Enter the last 4 digits (numbers only).")


def _enum_choices(enum_cls) -> list[tuple[str, str]]:
    return [(e.value, e.name.replace("_", " ").title()) for e in enum_cls]


def _prettify_kind(v: str) -> str:
    mapping = {
        "IRA": "IRA",
        "ROTH_IRA": "Roth IRA",
        "401K": "401(k)",
        "PENSION": "Pension",
        "BROKERAGE": "Brokerage",
        "CHECKING": "Checking",
        "SAVINGS": "Savings",
        "HYSA": "High-Yield Savings",
        "STOCK_OPTIONS": "Stock Options",
        "OTHER": "Other",
    }
    return mapping.get(v, v.title())


def _not_future(_form, field):
    if field.data and field.data > date.today():
        raise ValidationError("Date cannot be in the future.")


class ClientHouseholdForm(FlaskForm):
    """Household basics + Client 1 required, Client 2 optional."""

    household_label = StringField(
        "Household label",
        validators=[DataRequired(), Length(max=120)],
        description="How the household is referred to internally (e.g. 'The Smiths').",
    )

    # Client 1 (required)
    c1_first = StringField("First name", validators=[DataRequired(), Length(max=80)])
    c1_last = StringField("Last name", validators=[DataRequired(), Length(max=80)])
    c1_dob = DateField("Date of birth", validators=[DataRequired(), _not_future])
    c1_ssn_last4 = StringField("SSN (last 4)", validators=[DataRequired(), SSN_LAST4])
    c1_monthly_salary = DecimalField(
        "Monthly salary (after tax)",
        places=2,
        default=Decimal("0"),
        validators=[DataRequired(), NumberRange(min=0, max=1_000_000)],
    )

    # Client 2 (optional)
    c2_first = StringField("First name", validators=[Optional(), Length(max=80)])
    c2_last = StringField("Last name", validators=[Optional(), Length(max=80)])
    c2_dob = DateField("Date of birth", validators=[Optional(), _not_future])
    c2_ssn_last4 = StringField("SSN (last 4)", validators=[Optional(), SSN_LAST4])
    c2_monthly_salary = DecimalField(
        "Monthly salary (after tax)",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=1_000_000)],
    )

    monthly_expense_budget = DecimalField(
        "Agreed monthly expense budget (SACS outflow)",
        places=2,
        default=Decimal("0"),
        validators=[DataRequired(), NumberRange(min=0, max=1_000_000)],
    )
    private_reserve_target_override = DecimalField(
        "PR target override (optional)",
        places=2,
        validators=[Optional(), NumberRange(min=0)],
        description="Leave blank to auto-compute from expenses + deductibles.",
    )
    private_reserve_label = StringField(
        "Private-reserve label",
        default="PRIVATE RESERVE",
        validators=[DataRequired(), Length(max=60)],
        description="Rendered on both SACS pages (some clients use 'FICA ACCOUNT').",
    )
    trust_label = StringField(
        "Trust label",
        default="Family Trust",
        validators=[DataRequired(), Length(max=120)],
    )
    trust_property_address = TextAreaField(
        "Trust property address (for Zillow reference)",
        validators=[Optional(), Length(max=255)],
    )

    def validate(self, extra_validators=None) -> bool:  # type: ignore[override]
        base_ok = super().validate(extra_validators)
        if not base_ok:
            return False

        # Client-2 partial-fill guard: if any C2 field is set, C2 first+last+DOB are required.
        c2_fields = [
            self.c2_first.data,
            self.c2_last.data,
            self.c2_dob.data,
            self.c2_ssn_last4.data,
            self.c2_monthly_salary.data,
        ]
        c2_any = any(v not in (None, "") for v in c2_fields)
        if c2_any:
            for field, label in [
                (self.c2_first, "first name"),
                (self.c2_last, "last name"),
                (self.c2_dob, "date of birth"),
            ]:
                if not field.data:
                    field.errors.append(
                        f"Client 2 {label} is required when any Client 2 field is filled."
                    )
                    return False
        return True


class AccountForm(FlaskForm):
    """Add or edit a single account row."""

    section = SelectField(
        "Section",
        choices=_enum_choices(AccountSection),
        validators=[DataRequired()],
    )
    owner = SelectField(
        "Owner",
        choices=_enum_choices(AccountOwner),
        validators=[DataRequired()],
    )
    kind = SelectField(
        "Kind",
        choices=[(e.value, _prettify_kind(e.value)) for e in AccountKind],
        validators=[DataRequired()],
    )
    display_name = StringField("Label (shown on reports)", validators=[Optional(), Length(max=120)])
    custodian = StringField("Custodian", validators=[Optional(), Length(max=80)])
    last4 = StringField("Account # (last 4)", validators=[Optional(), LAST4_ACCT])
    order_idx = HiddenField(default="0")

    def validate(self, extra_validators=None) -> bool:  # type: ignore[override]
        if not super().validate(extra_validators):
            return False
        # Retirement accounts cannot be JOINT.
        if (
            self.section.data == AccountSection.RETIREMENT.value
            and self.owner.data == AccountOwner.JOINT.value
        ):
            self.owner.errors.append(
                "Retirement accounts must be owned by Client 1 or Client 2 — never joint."
            )
            return False
        return True


class LiabilityForm(FlaskForm):
    kind = SelectField(
        "Kind",
        choices=_enum_choices(LiabilityKind),
        validators=[DataRequired()],
    )
    label = StringField(
        "Label (shown on report)",
        validators=[DataRequired(), Length(max=120)],
        description="e.g. 'P Mortg', 'Mercedes', 'PNC'.",
    )
    interest_rate = DecimalField(
        "Interest rate (%)",
        places=3,
        validators=[Optional(), NumberRange(min=0, max=100)],
    )


class DeductibleForm(FlaskForm):
    label = StringField("Label", validators=[DataRequired(), Length(max=120)])
    amount = DecimalField(
        "Amount",
        places=2,
        validators=[DataRequired(), NumberRange(min=0)],
    )


class DeleteForm(FlaskForm):
    """Empty form for CSRF-protected delete/archive POSTs."""
