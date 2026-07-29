from app.domain.dates import now_sgt
from app.domain.types import Meal
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class MealAdjustment(db.Model):
    """DORMANT since owner decision (j) (2026-07-07): the manual ± was removed
    with the per-meal counts, and the indent is derived presence only (decision
    (bb) 2026-07-29 widened WHO is counted, not how). The table and model stay —
    dropping a table is riskier than ignoring one — but no route or service
    writes here anymore.

    Original design (P3b.5): S4's manual per-meal ± (people added/removed from
    a food order).

    Append-only, like the ledger: there is NO update or delete function or
    route anywhere for this model, and no unique(date, meal)
    constraint. A correction is a second, compensating row; the rows together
    ARE the audit trail. It is a persisted row (not a form one-shot) precisely
    so the ± survives a recompile of the live-derived counts. `reason` is
    mandatory — an unexplained change to a real food order is what it prevents.
    """

    __tablename__ = "meal_adjustment"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    meal = db.Column(db.Enum(Meal, values_callable=_values, name="meal"), nullable=False)
    # Signed count of people (+ adds, - removes); applied last over the derived base.
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    created_by = db.relationship("Person", foreign_keys=[created_by_id])

    def __repr__(self):
        return f"<MealAdjustment {self.id} {self.date} {self.meal.value} {self.delta:+d}>"
