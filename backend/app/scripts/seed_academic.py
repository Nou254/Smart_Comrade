"""
Seed Kenya geography (8 regions + 47 counties) and a demo institution.

Usage:
    python -m app.scripts.seed_academic
    python -m app.scripts.seed_academic --demo
"""
import argparse
import sys
from datetime import date

from app.db.session import SessionLocal
from app.models.academic import Region, County, Institution, School, Course, Unit


# 8 regions (former provinces) + their codes
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

# 47 counties grouped by region
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


def seed_geography(db) -> None:
    print("→ Seeding regions...")
    region_map: dict[str, Region] = {}
    for code, name in REGIONS:
        r = db.query(Region).filter(Region.code == code).first()
        if not r:
            r = Region(code=code, name=name)
            db.add(r); db.flush()
            print(f"   + {code} — {name}")
        region_map[code] = r

    print("→ Seeding counties...")
    for region_code, counties in COUNTIES_BY_REGION.items():
        region = region_map[region_code]
        for code, name in counties:
            c = db.query(County).filter(County.code == code).first()
            if not c:
                c = County(region_id=region.id, code=code, name=name)
                db.add(c); db.flush()
    db.commit()
    total = db.query(County).count()
    print(f"✅ Geography seeded. {len(REGIONS)} regions, {total} counties.")


def seed_demo(db) -> None:
    """Seed one demo institution with a school, course, units, and academic year."""
    from app.models.academic import AcademicYear, Semester

    nairobi = db.query(County).filter(County.code == "NRB-01").first()
    if not nairobi:
        print("⚠️  Nairobi county missing — run geography seed first.")
        return

    existing = db.query(Institution).filter(Institution.code == "JOOUST").first()
    if existing:
        print("ℹ  Demo institution already exists (JOOUST).")
        inst = existing
    else:
        inst = Institution(
            name="Jaramogi Oginga Odinga University of Science and Technology",
            short_name="JOOUST",
            code="JOOUST",
            type="UNIVERSITY",
            county_id=nairobi.id,
            status="active",
            email="info@jooust.ac.ke",
            website="https://www.jooust.ac.ke",
        )
        db.add(inst); db.flush()
        print("✅ Institution created: JOOUST")

    # School of Informatics
    school = db.query(School).filter(
        School.institution_id == inst.id, School.code == "SIIS"
    ).first()
    if not school:
        school = School(
            institution_id=inst.id,
            name="School of Informatics and Innovative Systems",
            code="SIIS",
            description="Computing, IT, and information sciences",
        )
        db.add(school); db.flush()
        print("✅ School created: SIIS")

    # BSc ICT
    course = db.query(Course).filter(
        Course.school_id == school.id, Course.code == "BSC-ICT"
    ).first()
    if not course:
        course = Course(
            school_id=school.id,
            name="Bachelor of Science in Information Communication Technology",
            code="BSC-ICT",
            duration_years=4,
        )
        db.add(course); db.flush()
        print("✅ Course created: BSc ICT")

    # Units
    units_data = [
        ("Introduction to Programming", "ICT-111", 1, 1),
        ("Discrete Mathematics", "ICT-112", 1, 1),
        ("Database Systems", "ICT-211", 2, 1),
        ("Computer Networks", "ICT-212", 2, 1),
        ("Software Engineering", "ICT-221", 2, 2),
    ]
    for name, code, yl, sn in units_data:
        exists = db.query(Unit).filter(
            Unit.course_id == course.id, Unit.code == code
        ).first()
        if not exists:
            db.add(Unit(
                course_id=course.id, name=name, code=code,
                year_level=yl, semester_number=sn,
            ))
    db.flush()
    print(f"✅ Units seeded: {len(units_data)}")

    # Academic Year
    ay = db.query(AcademicYear).filter(
        AcademicYear.institution_id == inst.id,
        AcademicYear.name == "2026/2027",
    ).first()
    if not ay:
        ay = AcademicYear(
            institution_id=inst.id, name="2026/2027",
            start_date=date(2026, 9, 1), end_date=date(2027, 8, 31),
            status="upcoming",
        )
        db.add(ay); db.flush()
        print("✅ Academic year created: 2026/2027")

    # Semesters
    for num, name, start, end in [
        (1, "Semester 1", date(2026, 9, 1), date(2026, 12, 20)),
        (2, "Semester 2", date(2027, 1, 10), date(2027, 5, 30)),
    ]:
        exists = db.query(Semester).filter(
            Semester.academic_year_id == ay.id, Semester.number == num
        ).first()
        if not exists:
            db.add(Semester(
                academic_year_id=ay.id, number=num, name=name,
                start_date=start, end_date=end, status="upcoming",
            ))
    db.commit()
    print("✅ Demo data seeded.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed academic structure.")
    parser.add_argument("--demo", action="store_true",
                        help="Also create a demo institution with school/course/units")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed_geography(db)
        if args.demo:
            seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())