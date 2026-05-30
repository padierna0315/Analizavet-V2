"""
Backfill appsheet_confirmed flag for existing patients.

One-shot management command. Run after deploy, before AppSheet traffic hits:
  python -m app.commands.backfill_appsheet_confirmed

Tags existing patients with valid demographics as AppSheet-confirmed.
Patients with placeholder demographics (Sin Tutor, Desconocida) remain
appsheet_confirmed=False — these were machine-created placeholders that
AppSheet never touched.

Supports --dry-run for verification.
"""

import asyncio
from sqlmodel import text
from app.database import AsyncSessionLocal


async def backfill(dry_run: bool = False) -> dict:
    """Backfill appsheet_confirmed=True for patients with valid demographics.

    Criteria:
      - owner_name is NOT NULL and NOT in ('Sin Tutor', 'Desconocida', '')
      - name is NOT NULL and NOT in ('', 'Desconocida')

    Returns:
        dict with 'updated', 'skipped', 'dry_run' counts.
    """
    update_sql = text("""
        UPDATE patient
        SET appsheet_confirmed = 1
        WHERE owner_name IS NOT NULL
          AND owner_name NOT IN ('Sin Tutor', 'Desconocida', '')
          AND name IS NOT NULL
          AND name NOT IN ('', 'Desconocida')
    """)

    count_sql = text("""
        SELECT COUNT(*) AS cnt
        FROM patient
        WHERE owner_name IS NOT NULL
          AND owner_name NOT IN ('Sin Tutor', 'Desconocida', '')
          AND name IS NOT NULL
          AND name NOT IN ('', 'Desconocida')
    """)

    skip_sql = text("""
        SELECT COUNT(*) AS cnt
        FROM patient
        WHERE appsheet_confirmed = 0
    """)

    async with AsyncSessionLocal() as session:
        # Count how many would be updated
        result = await session.execute(count_sql)
        to_update = result.scalar_one()

        if dry_run:
            # Count how many would remain unconfirmed
            result = await session.execute(skip_sql)
            would_skip = result.scalar_one()
            print(f"[DRY RUN] Would tag {to_update} patients as confirmed")
            print(f"[DRY RUN] {would_skip} patients would remain unconfirmed")
            await session.rollback()
            return {"updated": 0, "skipped": would_skip, "dry_run": True}

        # Execute the update
        result = await session.execute(update_sql)
        await session.commit()

        # Count remaining unconfirmed
        result = await session.execute(skip_sql)
        remaining = result.scalar_one()

        updated = to_update
        print(f"Tagged {updated} patients as appsheet_confirmed=True")
        print(f"{remaining} patients remain appsheet_confirmed=False")

        return {"updated": updated, "skipped": remaining, "dry_run": False}


def rollback() -> dict:
    """Reset all patients to appsheet_confirmed=False."""
    import asyncio

    async def _rollback():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("UPDATE patient SET appsheet_confirmed = 0")
            )
            await session.commit()
            return {"reset": True}

    return asyncio.run(_rollback())


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv
    result = asyncio.run(backfill(dry_run=dry_run))
    print(f"Result: {result}")
