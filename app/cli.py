import csv

import click

from app.domain.types import Appointment, CompanyRole, Rank, Service
from app.extensions import db
from app.models import Person


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
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                username = row["username"].strip().lower()
                if db.session.query(Person.id).filter_by(username=username).first():
                    skipped += 1
                    continue
                person = Person(
                    username=username,
                    display_name=row["display_name"].strip(),
                    rank=Rank(row["rank"].strip()),
                    appointment=Appointment(row["appointment"].strip()),
                    company_role=(
                        CompanyRole(row["company_role"].strip())
                        if row["company_role"].strip()
                        else None
                    ),
                    platoon=int(row["platoon"]) if row["platoon"].strip() else None,
                    service=Service(row["service"].strip()),
                    stay_out=row["stay_out"].strip() == "1",
                    is_admin=row.get("is_admin", "").strip() == "1",
                )
                person.set_password(default_password)
                db.session.add(person)
                created += 1
        db.session.commit()
        click.echo(f"Seeded {created} people ({skipped} already existed).")
