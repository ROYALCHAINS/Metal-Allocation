"""
create_user.py
Royal Metal Allocation System — Python port

Command-line tool to provision or update a user account. There is no
signup page — per CLAUDE.md section 6, rule 11 (closed roster), accounts
are created here, out of band, by an administrator running this script
directly against the database. This mirrors legacy's model of hand-editing
Config.gs's ADMIN_EMAILS/OPERATOR_PARTIES.

The password is read interactively (getpass, not echoed, not passed as a
command-line argument) so it never appears in shell history or process
listings.

Usage (from inside this directory):
    python create_user.py --email admin@royalchains.com --display-name "Admin" --role admin
    python create_user.py --email op@royalchains.com --display-name "Op" --role operator \\
        --party "Royal Chain"

`--party` may be repeated. It grants an operator visibility of that party's
sectors and nothing else (CLAUDE.md section 6, rule 8). Administrators are
unrestricted, so --party is not needed for them. Passing --party replaces the
user's existing party grants rather than adding to them, so the command
describes the final state.
"""

import argparse
import getpass
import sys

from sqlalchemy import delete, select

from database import SessionLocal
from models.party import Party
from models.user import AppUser, UserPartyScope
from repository.user_repo import get_user_by_email
from services.password_service import hash_password
from services.validation_service import normalize_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update an RMAS user account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", choices=["admin", "operator"], required=True)
    parser.add_argument("--denied", action="store_true", help="Set the deny flag (CLAUDE.md rule 9).")
    parser.add_argument(
        "--party",
        action="append",
        default=[],
        metavar="PARTY_NAME",
        help="Grant visibility of this party's sectors. Repeatable. Replaces existing grants.",
    )
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        raise SystemExit(1)
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)

    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        existing = get_user_by_email(db, email)
        password_hash = hash_password(password)
        is_admin = args.role == "admin"
        if existing is not None:
            existing.display_name = args.display_name
            existing.is_admin = is_admin
            existing.admin_denied = args.denied
            existing.password_hash = password_hash
            print(f"Updated existing user: {email}")
        else:
            user = AppUser(
                email=email,
                display_name=args.display_name,
                is_admin=is_admin,
                admin_denied=args.denied,
                password_hash=password_hash,
            )
            db.add(user)
            db.flush()
            existing = user
            print(f"Created user: {email}")

        if args.party:
            _set_party_scope(db, existing, args.party)

        db.commit()
    finally:
        db.close()


def _set_party_scope(db, user: AppUser, party_names: list[str]) -> None:
    """Replace the user's party grants. Refuses an unknown party name."""
    resolved = []
    for name in party_names:
        key = normalize_key(name)
        party = db.scalar(select(Party).where(Party.party_key == key))
        if party is None:
            known = db.scalars(select(Party.party_name).order_by(Party.party_name)).all()
            raise SystemExit(
                f"ERROR: no party named {name!r}. Known parties: {', '.join(known)}"
            )
        resolved.append(party)

    db.execute(delete(UserPartyScope).where(UserPartyScope.user_id == user.user_id))
    for party in resolved:
        db.add(UserPartyScope(user_id=user.user_id, party_id=party.party_id))

    print(f"  party scope: {', '.join(p.party_name for p in resolved)}")


if __name__ == "__main__":
    main()
