import csv
from datetime import date

import click

from app.domain.types import Appointment, CompanyRole, Rank, Service
from app.extensions import db
from app.models import Person, PublicHoliday

REQUIRED_COLUMNS = {
    "username",
    "display_name",
    "rank",
    "appointment",
    "company_role",
    "platoon",
    "service",
    "stay_out",
}


def register_cli(app):
    @app.cli.command("seed-people")
    @click.argument("csv_path", type=click.Path(exists=True))
    @click.option(
        "--default-password",
        default="ChangeMe123!",
        show_default=True,
        help="Initial password; every account must change it at first login.",
    )
    def seed_people(csv_path, default_password):
        """Load people from a CSV, skipping usernames that already exist."""
        created = skipped = 0
        # utf-8-sig: Excel's "CSV UTF-8" export prefixes a BOM that would
        # otherwise glue itself onto the first header name.
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise click.ClickException(f"CSV is missing columns: {sorted(missing)}")
            for lineno, row in enumerate(reader, start=2):
                def col(name):
                    return (row.get(name) or "").strip()

                username = col("username").lower()
                if not username:
                    raise click.ClickException(f"Row {lineno} is malformed (no username)")
                if db.session.query(Person.id).filter_by(username=username).first():
                    skipped += 1
                    continue
                try:
                    person = Person(
                        username=username,
                        display_name=col("display_name"),
                        rank=Rank(col("rank")),
                        appointment=Appointment(col("appointment")),
                        company_role=CompanyRole(col("company_role")) if col("company_role") else None,
                        platoon=int(col("platoon")) if col("platoon") else None,
                        service=Service(col("service")),
                        stay_out=col("stay_out") == "1",
                        is_admin=col("is_admin") == "1",
                    )
                except ValueError as exc:
                    raise click.ClickException(f"Row {lineno} ({username}): {exc}")
                person.set_password(default_password)
                db.session.add(person)
                created += 1
        db.session.commit()
        click.echo(f"Seeded {created} people ({skipped} already existed).")

    @app.cli.command("seed-holidays")
    @click.argument("csv_path", type=click.Path(exists=True))
    def seed_holidays(csv_path):
        """Load public holidays from a CSV (date,name), skipping existing dates."""
        created = skipped = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or {"date", "name"} - set(reader.fieldnames):
                raise click.ClickException("CSV must have 'date' and 'name' columns")
            for lineno, row in enumerate(reader, start=2):
                raw = (row.get("date") or "").strip()
                try:
                    day = date.fromisoformat(raw)
                except ValueError:
                    raise click.ClickException(f"Row {lineno}: bad date {raw!r} (want YYYY-MM-DD)")
                if db.session.query(PublicHoliday.id).filter_by(date=day).first():
                    skipped += 1
                    continue
                db.session.add(PublicHoliday(date=day, name=(row.get("name") or "").strip()))
                created += 1
        db.session.commit()
        click.echo(f"Seeded {created} holidays ({skipped} already existed).")
