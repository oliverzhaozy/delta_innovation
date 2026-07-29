import csv
from datetime import date
from decimal import Decimal, InvalidOperation

import click

from app.domain.types import Appointment, BalanceKind, CompanyRole, LedgerSource, Rank, Service
from app.extensions import db
from app.models import LedgerEntry, Person, PublicHoliday
from app.services import ledger_service, purge_service

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
                        # Optional column, like is_admin: absent -> not exempt.
                        duty_exempt=col("duty_exempt") == "1",
                        meals_opt_in=col("meals_opt_in") == "1",
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

    @app.cli.command("seed-balances")
    @click.argument("csv_path", type=click.Path(exists=True))
    @click.option("--by", "by_username", required=True, help="Username recorded as the entering S3/admin.")
    def seed_balances(csv_path, by_username):
        """Load opening OFF/OIL balances (CSV: username,off_days,oil_days).

        Skips anyone who already has ledger entries — this is a rollout tool,
        not a correction tool (use the ledger UI for corrections).
        """
        actor = db.session.query(Person).filter_by(username=by_username.lower()).first()
        if actor is None:
            raise click.ClickException(f"No such user: {by_username}")
        created = skipped = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or {"username", "off_days", "oil_days"} - set(reader.fieldnames):
                raise click.ClickException("CSV must have username,off_days,oil_days columns")
            for lineno, row in enumerate(reader, start=2):
                username = (row.get("username") or "").strip().lower()
                person = db.session.query(Person).filter_by(username=username).first()
                if person is None:
                    raise click.ClickException(f"Row {lineno}: no such user {username!r}")
                if db.session.query(LedgerEntry.id).filter_by(person_id=person.id).first():
                    skipped += 1
                    continue
                for column, kind in (("off_days", BalanceKind.OFF), ("oil_days", BalanceKind.OIL)):
                    raw = (row.get(column) or "0").strip()
                    try:
                        days = Decimal(raw)
                    except InvalidOperation:
                        raise click.ClickException(f"Row {lineno}: bad number {raw!r} in {column}")
                    if days % Decimal("0.5") != 0:
                        raise click.ClickException(f"Row {lineno}: {column} must be a multiple of 0.5")
                    if days:
                        ledger_service.post_entry(
                            person_id=person.id,
                            kind=kind,
                            delta_half_days=int(days * 2),
                            reason="Opening balance (rollout)",
                            source=LedgerSource.MANUAL,
                            created_by_id=actor.id,
                        )
                created += 1
        db.session.commit()
        click.echo(f"Opening balances set for {created} people ({skipped} skipped — already had entries).")

    @app.cli.command("purge")
    @click.option(
        "--before",
        required=True,
        type=click.DateTime(formats=["%Y-%m-%d"]),
        help="Cutoff date (YYYY-MM-DD); rows that fully ended before this go.",
    )
    @click.option("--by", "by_username", required=True, help="Active username to own carry-forward rows.")
    @click.option(
        "--execute/--dry-run",
        "do_execute",
        default=False,
        help="Dry-run (default) reports counts and writes nothing; --execute performs the purge.",
    )
    def purge(before, by_username, do_execute):
        """Annual retention purge: drop rows that fully ended before --before.

        Destructive, so shell-only (no route). The ledger is collapsed, not
        deleted — balances are preserved and verified identical (A10).
        """
        cutoff = before.date()
        # Resolve --by in both modes so an unknown/inactive username fails before
        # anything is touched (dry-run stays read-only either way).
        actor = (
            db.session.query(Person)
            .filter_by(username=by_username.lower(), is_active=True)
            .first()
        )
        if actor is None:
            raise click.ClickException(f"No active user: {by_username}")
        if do_execute:
            result = purge_service.execute(cutoff, actor=actor)
            _echo_purge(result)
            click.echo("Balances verified identical.")
        else:
            result = purge_service.plan(cutoff)
            _echo_purge(result)
            click.echo("Dry run — nothing was deleted.")


def _echo_purge(result):
    click.echo("Rows to remove:")
    for table, count in result.counts:
        click.echo(f"  {table}: {count}")
    if result.carry_forwards:
        click.echo("Carry-forward ledger rows:")
        for person_id, kind, total in result.carry_forwards:
            click.echo(f"  person {person_id} {kind.value}: {total:+d} half-days")
