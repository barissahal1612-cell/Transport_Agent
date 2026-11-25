"""CLI: python -m ingest.run_ingest [--file yol] [--apply] [--seed]   (scripts/ dizininden)

Varsayılan dry-run'dır: AWS çağrısı yapılmaz. Gerçek yazma yalnızca --apply ile.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from logistic_ai_data.dynamo_keys import DEFAULT_KB_TABLE, KB_TABLE_ENV

from .excel_reader import read_workbook
from .loader import load_workbook_data
from .seed import dynamo_repositories, seed_workbook

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "Data" / "Agent_AWS_2026-11-24.xlsx"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Excel -> logistic-ai-kb yükleyici (Data_Store)")
    p.add_argument("--file", type=Path, default=DEFAULT_FILE, help="Excel dosyası yolu")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="varsayılan: yazma yok, AWS çağrısı yok")
    mode.add_argument("--apply", action="store_true", help="DynamoDB'ye gerçekten yaz")
    p.add_argument("--seed", action="store_true",
                   help="kullanıcı (role_user) ve izin (permissions) tohumlamasını da çalıştır")
    args = p.parse_args(argv)

    if not args.file.is_file():
        print(f"Dosya bulunamadı: {args.file}", file=sys.stderr)
        return 2
    wb = read_workbook(args.file)
    table = None
    if args.apply:
        import boto3  # yalnızca --apply

        table = boto3.resource("dynamodb").Table(os.environ.get(KB_TABLE_ENV, DEFAULT_KB_TABLE))
    report = load_workbook_data(wb, apply=args.apply, table=table)
    print(report.render())
    if args.seed:
        seed_report = seed_workbook(wb, apply=args.apply,
                                    repo_factory=dynamo_repositories if args.apply else None)
        print("\n--- Tohumlama (seed) ---")
        print(seed_report.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
