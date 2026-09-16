"""
Dump the contents of multiple project files into a single .txt file
for easy sharing / inspection.

Usage:
    python dump_files.py
    python dump_files.py --out my_dump.txt
"""
import argparse
import os
from datetime import datetime
from pathlib import Path


FILES = [
    # ── Core ────────────────────────────────────────────────
    "app/core/config.py",
    "app/core/notifications.py",
    "app/core/security.py",

    # ── DB ──────────────────────────────────────────────────
    "app/db/session.py",

    # ── Models ──────────────────────────────────────────────
    "app/models/__init__.py",
    "app/models/base.py",
    "app/models/user.py",
    "app/models/role.py",
    "app/models/auth_extension.py",
    "app/models/auth_audit.py",
    "app/models/two_factor.py",
    "app/models/group.py",
    "app/models/academic.py",
    "app/models/admin_action.py",
    "app/models/system_config.py",
    "app/models/admin_invitation.py",
    "app/models/upload.py",

    # ── Schemas ─────────────────────────────────────────────
    "app/schemas/__init__.py",
    "app/schemas/user.py",
    "app/schemas/auth_extra.py",
    "app/schemas/admin.py",
    "app/schemas/role.py",
    "app/schemas/group.py",
    "app/schemas/academic.py",
    "app/schemas/upload.py",

    # ── Services ────────────────────────────────────────────
    "app/services/__init__.py",
    "app/services/auth_service.py",
    "app/services/session_service.py",
    "app/services/role_service.py",
    "app/services/audit_service.py",
    "app/services/verification_service.py",
    "app/services/two_factor_service.py",
    "app/services/admin_service.py",
    "app/services/admin_audit_service.py",
    "app/services/jurisdiction_service.py",
    "app/services/system_config_service.py",
    "app/services/academic_service.py",
    "app/services/group_service.py",
    "app/services/upload_service.py",
    "app/services/ocr_service.py",
    "app/services/extraction_service.py",

    # ── API ─────────────────────────────────────────────────
    "app/api/__init__.py",
    "app/api/auth.py",
    "app/api/admin.py",
    "app/api/admin_roles.py",
    "app/api/academic.py",
    "app/api/group.py",
    "app/api/upload.py",
    "app/api/deps.py",

    # ── Main ────────────────────────────────────────────────
    "app/main.py",

    # ── Config files ────────────────────────────────────────
    "requirements.txt",
    ".env.example",
]


SEPARATOR = "=" * 80


def dump(out_path: Path, base: Path) -> None:
    lines: list[str] = []
    lines.append(f"# Smart Comrade — File Dump")
    lines.append(f"# Generated: {datetime.now().isoformat()}")
    lines.append(f"# Working directory: {base}")
    lines.append("")

    found = 0
    missing: list[str] = []

    for rel in FILES:
        abs_path = base / rel
        lines.append(SEPARATOR)
        lines.append(f"# FILE: {rel}")
        lines.append(SEPARATOR)

        if not abs_path.exists():
            lines.append("<<< FILE NOT FOUND >>>")
            lines.append("")
            missing.append(rel)
            continue

        try:
            content = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = abs_path.read_text(encoding="latin-1")
            except Exception as e:
                lines.append(f"<<< READ ERROR: {e} >>>")
                lines.append("")
                continue

        # Cap individual files at 2MB to avoid gigantic dumps
        if len(content) > 2_000_000:
            content = content[:2_000_000] + "\n\n<<< TRUNCATED AT 2MB >>>\n"

        lines.append(content.rstrip("\n"))
        lines.append("")
        found += 1

    # Missing files summary at the top
    header = []
    header.append(f"# Files found:   {found}")
    header.append(f"# Files missing: {len(missing)}")
    if missing:
        header.append("#")
        header.append("# Missing files:")
        for m in missing:
            header.append(f"#   - {m}")
    header.append("")

    final = "\n".join(lines[:4] + header + lines[4:])

    out_path.write_text(final, encoding="utf-8")
    print(f"Wrote {found} files to {out_path}")
    if missing:
        print(f"Missing {len(missing)} files:")
        for m in missing:
            print(f"  - {m}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="project_dump.txt", help="Output file")
    parser.add_argument("--base", default=".", help="Base directory")
    args = parser.parse_args()

    base = Path(args.base).resolve()
    out = Path(args.out).resolve()

    dump(out, base)


if __name__ == "__main__":
    main()