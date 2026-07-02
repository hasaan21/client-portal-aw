"""Report entry form (meeting-date only). Balance rows are parsed manually
from request.form because their count is dynamic (one per Account / Liability)."""

from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField
from wtforms.validators import DataRequired, ValidationError


class NewReportForm(FlaskForm):
    meeting_date = DateField(
        "Meeting date",
        validators=[DataRequired()],
        default=date.today,
    )

    def validate_meeting_date(self, field):
        if field.data and field.data > date.today().replace(year=date.today().year + 1):
            raise ValidationError("Meeting date more than a year in the future?")
