"""Form pieces more than one blueprint needs.

Deliberately shallow: something lands here only once two or more blueprints
already state it identically, so the copies cannot drift into two rules or two
messages for what users experience as one.
"""
from wtforms.validators import ValidationError

from app.services import event_service


class EndDateOrderMixin:
    """`end_date` may not precede `start_date` — one rule, one message, for the
    three date-range forms (leave, overseas, MC). The CHECK constraint on each
    table is the real guard; this is the field error the user sees first.

    WTForms resolves `validate_<field>` off the form CLASS, so mixing this in
    works, but the form must still declare both `start_date` and `end_date`
    itself — the mixin contributes no fields.
    """

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("End date is before start date.")


def set_people_choices(form, roster=None):
    """Fill `form.people.choices` at REQUEST time, not at class definition — who
    is on the roster and which platoon they hold changes day to day, unlike the
    fixed category choices. Only the `people` field is set, so
    `SelectMultipleField.pre_validate` turns an unknown id into a clean field
    error rather than letting it reach the DB. `roster` narrows the list for a
    picker that draws from a subset of the company.
    """
    people = event_service.active_roster() if roster is None else roster
    form.people.choices = [(p.id, f"{p.rank.value} {p.display_name}") for p in people]
