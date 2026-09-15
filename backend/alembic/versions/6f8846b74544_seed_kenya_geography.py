"""seed kenya geography

Revision ID: auto
Revises: auto
Create Date: auto

Seeds 8 regions and 47 counties of Kenya.
Idempotent: skips if regions already exist.
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "6f8846b74544"
down_revision = "4176e5e06c7d"
branch_labels = None
depends_on = None


REGIONS = [
    ("NRB", "Nairobi"),
    ("CEN", "Central"),
    ("CST", "Coast"),
    ("EAS", "Eastern"),
    ("N-E", "North Eastern"),
    ("RIF", "Rift Valley"),
    ("WES", "Western"),
    ("NYA", "Nyanza"),
]

COUNTIES_BY_REGION = {
    "NRB": [("NRB-01", "Nairobi")],
    "CEN": [
        ("CEN-01", "Kiambu"), ("CEN-02", "Kirinyaga"), ("CEN-03", "Murang'a"),
        ("CEN-04", "Nyandarua"), ("CEN-05", "Nyeri"),
    ],
    "CST": [
        ("CST-01", "Kilifi"), ("CST-02", "Kwale"), ("CST-03", "Lamu"),
        ("CST-04", "Mombasa"), ("CST-05", "Taita-Taveta"), ("CST-06", "Tana River"),
    ],
    "EAS": [
        ("EAS-01", "Embu"), ("EAS-02", "Isiolo"), ("EAS-03", "Kitui"),
        ("EAS-04", "Machakos"), ("EAS-05", "Makueni"), ("EAS-06", "Marsabit"),
        ("EAS-07", "Meru"), ("EAS-08", "Tharaka-Nithi"),
    ],
    "N-E": [
        ("NE-01", "Garissa"), ("NE-02", "Mandera"), ("NE-03", "Wajir"),
    ],
    "RIF": [
        ("RIF-01", "Baringo"), ("RIF-02", "Bomet"), ("RIF-03", "Elgeyo-Marakwet"),
        ("RIF-04", "Kajiado"), ("RIF-05", "Kericho"), ("RIF-06", "Laikipia"),
        ("RIF-07", "Nakuru"), ("RIF-08", "Nandi"), ("RIF-09", "Narok"),
        ("RIF-10", "Samburu"), ("RIF-11", "Trans Nzoia"), ("RIF-12", "Turkana"),
        ("RIF-13", "Uasin Gishu"), ("RIF-14", "West Pokot"),
    ],
    "WES": [
        ("WES-01", "Bungoma"), ("WES-02", "Busia"), ("WES-03", "Kakamega"),
        ("WES-04", "Vihiga"),
    ],
    "NYA": [
        ("NYA-01", "Homa Bay"), ("NYA-02", "Kisii"), ("NYA-03", "Kisumu"),
        ("NYA-04", "Migori"), ("NYA-05", "Nyamira"), ("NYA-06", "Siaya"),
    ],
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(sa.text("SELECT COUNT(*) FROM regions")).scalar()
    if existing and existing > 0:
        print(f"   Regions already seeded ({existing} rows). Skipping.")
        return

    now = datetime.now(timezone.utc)

    region_ids: dict[str, str] = {}
    for code, name in REGIONS:
        region_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO regions (id, code, name, created_at, updated_at) "
                "VALUES (:id, :code, :name, :now, :now)"
            ),
            {"id": region_id, "code": code, "name": name, "now": now},
        )
        region_ids[code] = region_id
        print(f"   + region {code} — {name}")

    county_count = 0
    for region_code, counties in COUNTIES_BY_REGION.items():
        parent = region_ids[region_code]
        for code, name in counties:
            conn.execute(
                sa.text(
                    "INSERT INTO counties (id, region_id, code, name, created_at, updated_at) "
                    "VALUES (:id, :region_id, :code, :name, :now, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "region_id": parent,
                    "code": code,
                    "name": name,
                    "now": now,
                },
            )
            county_count += 1

    print(f"   + {county_count} counties inserted")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM counties WHERE code LIKE 'NRB-%' OR code LIKE 'CEN-%' "
                         "OR code LIKE 'CST-%' OR code LIKE 'EAS-%' OR code LIKE 'NE-%' "
                         "OR code LIKE 'RIF-%' OR code LIKE 'WES-%' OR code LIKE 'NYA-%'"))
    conn.execute(sa.text("DELETE FROM regions WHERE code IN "
                         "('NRB','CEN','CST','EAS','N-E','RIF','WES','NYA')"))