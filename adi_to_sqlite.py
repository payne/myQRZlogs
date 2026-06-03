#!/usr/bin/env python3
"""Convert an ADIF (.adi) logbook to a SQLite3 database for use with datasette-lite."""

import re
import sqlite3
import sys
from pathlib import Path


def parse_adif(text):
    """Parse ADIF format into a list of QSO record dicts."""
    # Skip header (everything before <eoh>)
    eoh = re.search(r'<eoh>', text, re.IGNORECASE)
    if eoh:
        text = text[eoh.end():]

    records = []
    field_pattern = re.compile(r'<([^:>]+)(?::(\d+)(?::[^>]*)?)?>([^<]*)', re.IGNORECASE)

    for block in re.split(r'<eor>', text, flags=re.IGNORECASE):
        block = block.strip()
        if not block:
            continue
        record = {}
        for match in field_pattern.finditer(block):
            name = match.group(1).lower()
            length = int(match.group(2)) if match.group(2) else None
            value = match.group(3)
            if length is not None:
                value = value[:length]
            value = value.strip()
            if value:
                record[name] = value
        if record:
            records.append(record)
    return records


def infer_type(values):
    """Return 'REAL', 'INTEGER', or 'TEXT' based on sample values."""
    non_empty = [v for v in values if v]
    if not non_empty:
        return 'TEXT'
    try:
        [int(v) for v in non_empty]
        return 'INTEGER'
    except ValueError:
        pass
    try:
        [float(v) for v in non_empty]
        return 'REAL'
    except ValueError:
        pass
    return 'TEXT'


def build_database(records, db_path):
    # Collect all field names preserving a sensible order
    all_fields = []
    seen = set()
    for rec in records:
        for k in rec:
            if k not in seen:
                all_fields.append(k)
                seen.add(k)

    # Infer column types
    col_types = {}
    for field in all_fields:
        values = [rec.get(field, '') for rec in records]
        col_types[field] = infer_type(values)

    # Promote key date/time fields to TEXT explicitly (they look like integers but aren't)
    for field in ('qso_date', 'qso_date_off', 'qrzcom_qso_download_date',
                  'time_on', 'time_off', 'gridsquare', 'my_gridsquare',
                  'band', 'band_rx', 'call', 'mode', 'state', 'country',
                  'cont', 'my_state', 'my_country', 'my_cnty', 'my_city',
                  'qth', 'my_name', 'name', 'station_callsign', 'email'):
        if field in col_types:
            col_types[field] = 'TEXT'

    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    col_defs = ', '.join(f'"{f}" {col_types[f]}' for f in all_fields)
    cur.execute(f'CREATE TABLE qsos (id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})')

    placeholders = ', '.join('?' for _ in all_fields)
    col_names = ', '.join(f'"{f}"' for f in all_fields)
    insert_sql = f'INSERT INTO qsos ({col_names}) VALUES ({placeholders})'

    for rec in records:
        row = []
        for field in all_fields:
            val = rec.get(field)
            if val is None:
                row.append(None)
            elif col_types[field] == 'INTEGER':
                row.append(int(val))
            elif col_types[field] == 'REAL':
                row.append(float(val))
            else:
                row.append(val)
        cur.execute(insert_sql, row)

    # Useful indexes for common queries
    for idx_col in ('call', 'qso_date', 'band', 'mode', 'state', 'country', 'dxcc'):
        if idx_col in all_fields:
            cur.execute(f'CREATE INDEX idx_{idx_col} ON qsos ("{idx_col}")')

    con.commit()
    con.close()
    return len(records), all_fields


def main():
    adi_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('logbook.adi')
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else adi_path.with_suffix('.db')

    print(f'Reading {adi_path} ...')
    text = adi_path.read_text(encoding='utf-8', errors='replace')

    print('Parsing ADIF records ...')
    records = parse_adif(text)
    print(f'Found {len(records)} QSO records')

    print(f'Building {db_path} ...')
    count, fields = build_database(records, db_path)

    print(f'Done — {count} rows, {len(fields)} columns')
    print(f'Columns: {", ".join(fields)}')
    print()
    print('To explore with datasette-lite, visit:')
    print('  https://lite.datasette.io/')
    print(f'  Then drag-and-drop {db_path} into the browser.')


if __name__ == '__main__':
    main()
