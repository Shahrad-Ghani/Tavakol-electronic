#!/usr/bin/env python3
from pathlib import Path
from reporting.excel_report import generate_report

if __name__ == "__main__":
    path = generate_report(Path(__file__).resolve().parent)
    print(path)
