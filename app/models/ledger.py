from app.domain.dates import now_sgt
from app.domain.types import BalanceKind, LedgerSource
from app.extensions import db


def _values(enum_cls):
    return [member.value for member in enum_cls]


class LedgerEntry(db.Model):
    """Append-only. Balance = SUM(delta_half_days); no stored balance column
    exists anywhere, so the balance cannot drift. Corrections are new REVERSAL
    rows, never edits or deletes.
    """

    __tablename__ = "ledger_entry"

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False, index=True)
    kind = db.Column(db.Enum(BalanceKind, values_callable=_values, name="balance_kind"), nullable=False)
    # Integer half-days (full day = 2): exact arithmetic, no floats in the ledger.
    delta_half_days = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    source = db.Column(db.Enum(LedgerSource, values_callable=_values, name="ledger_source"), nullable=False)
    leave_request_id = db.Column(db.Integer, db.ForeignKey("leave_request.id"), index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("person.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_sgt)

    person = db.relationship("Person", foreign_keys=[person_id])
    created_by = db.relationship("Person", foreign_keys=[created_by_id])
    leave_request = db.relationship("LeaveRequest", foreign_keys=[leave_request_id])

    __table_args__ = (
        # Backstop against double-deduction: one APPROVAL debit per request+kind.
        # Scoped to LEAVE_APPROVAL so REVERSAL rows may legitimately repeat — an
        # amendment (early return) posts a partial reversal, and a later cancel
        # posts another. (MANUAL rows have a NULL request id, so they never match
        # this partial index and stay unlimited.)
        db.Index(
            "uq_ledger_request_approval_kind",
            "leave_request_id",
            "kind",
            unique=True,
            sqlite_where=db.text("source = 'LEAVE_APPROVAL'"),
        ),
    )

    def __repr__(self):
        return f"<LedgerEntry {self.id} p{self.person_id} {self.kind.value} {self.delta_half_days:+d}>"
