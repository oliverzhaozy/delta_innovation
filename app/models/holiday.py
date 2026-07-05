from app.extensions import db


class PublicHoliday(db.Model):
    """Singapore public holidays. Feeds working-day deduction now, roster skip
    days in Phase 4. Seeded from CSV; admin keys new years as MOM gazettes them.
    """

    __tablename__ = "public_holiday"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)

    @classmethod
    def dates_between(cls, start, end) -> frozenset:
        rows = db.session.query(cls.date).filter(cls.date >= start, cls.date <= end).all()
        return frozenset(r.date for r in rows)
