#!/usr/bin/env python3
"""Sync QSO confirmation status from QRZ.com logbook to local SQLite database."""

import html
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime


def get_api_key():
    """Get QRZ API key from environment variable or .env file."""
    api_key = os.environ.get('QRZ_API_KEY')
    if api_key:
        return api_key

    # Try reading from .env file
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('QRZ_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"\'')

    return None


def qrz_api_request(api_key, action, **params):
    """Make a request to the QRZ Logbook API."""
    url = 'https://logbook.qrz.com/api'

    data = {
        'KEY': api_key,
        'ACTION': action,
    }
    data.update(params)

    encoded = urllib.parse.urlencode(data).encode('utf-8')

    req = urllib.request.Request(url, data=encoded, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')

    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode('utf-8', errors='replace')


def parse_qrz_response(response_text):
    """Parse QRZ API response into a dict."""
    # Unescape HTML entities (QRZ returns &lt; &gt; etc.)
    response_text = html.unescape(response_text)

    result = {}
    # QRZ returns key=value pairs separated by &
    # But ADIF field contains & in the data, so we need to be careful
    # First extract RESULT, COUNT, and ADIF separately

    # Find RESULT
    result_match = re.search(r'RESULT=(\w+)', response_text)
    if result_match:
        result['RESULT'] = result_match.group(1)

    # Find COUNT
    count_match = re.search(r'COUNT=(\d+)', response_text)
    if count_match:
        result['COUNT'] = count_match.group(1)

    # Find REASON (for errors)
    reason_match = re.search(r'REASON=([^&]+)', response_text)
    if reason_match:
        result['REASON'] = reason_match.group(1)

    # Find ADIF - everything after ADIF=
    adif_match = re.search(r'ADIF=(.+)', response_text, re.DOTALL)
    if adif_match:
        result['ADIF'] = adif_match.group(1)

    return result


def parse_adif_record(adif_text):
    """Parse a single ADIF record into a dict."""
    record = {}
    field_pattern = re.compile(r'<([^:>]+)(?::(\d+)(?::[^>]*)?)?>([^<]*)', re.IGNORECASE)

    for match in field_pattern.finditer(adif_text):
        name = match.group(1).lower()
        length = int(match.group(2)) if match.group(2) else None
        value = match.group(3)
        if length is not None:
            value = value[:length]
        value = value.strip()
        if value:
            record[name] = value

    return record


def fetch_qrz_logbook(api_key):
    """Fetch all QSOs from QRZ logbook."""
    print("Fetching QSOs from QRZ.com...")

    response = qrz_api_request(api_key, 'FETCH', OPTION='ALL')
    parsed = parse_qrz_response(response)

    if parsed.get('RESULT') == 'FAIL':
        error = parsed.get('REASON', 'Unknown error')
        raise Exception(f"QRZ API error: {error}")

    count = int(parsed.get('COUNT', 0))
    print(f"QRZ reports {count} QSOs in logbook")

    all_qsos = []

    # Parse ADIF data from response
    adif_data = parsed.get('ADIF', '')
    if adif_data:
        # Split by <eor> to get individual records
        for record_text in re.split(r'<eor>', adif_data, flags=re.IGNORECASE):
            record_text = record_text.strip()
            if record_text:
                qso = parse_adif_record(record_text)
                if qso:
                    all_qsos.append(qso)

    print(f"Parsed {len(all_qsos)} QSO records from QRZ")
    return all_qsos


def update_confirmations(db_path, qrz_qsos):
    """Update local database with confirmation status from QRZ."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if we need to add confirmation columns
    cursor.execute("PRAGMA table_info(qsos)")
    columns = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ('lotw_qsl_rcvd', 'TEXT'),
        ('lotw_qslrdate', 'TEXT'),
        ('qrzcom_qso_upload_status', 'TEXT'),
        ('app_qrzlog_qsldate', 'TEXT'),
    ]

    for col_name, col_type in new_columns:
        if col_name not in columns:
            print(f"Adding column: {col_name}")
            cursor.execute(f'ALTER TABLE qsos ADD COLUMN "{col_name}" {col_type}')

    conn.commit()

    # Build lookup dict for QRZ QSOs
    # Key: (call, qso_date, time_on, band) -> QSO record
    qrz_lookup = {}
    for qso in qrz_qsos:
        call = qso.get('call', '').upper()
        qso_date = qso.get('qso_date', '')
        time_on = qso.get('time_on', '')[:4] if qso.get('time_on') else ''  # Use HHMM
        band = qso.get('band', '').upper()

        key = (call, qso_date, time_on, band)
        qrz_lookup[key] = qso

    # Fetch local QSOs
    cursor.execute("SELECT id, call, qso_date, time_on, band FROM qsos")
    local_qsos = cursor.fetchall()

    updated = 0
    confirmed_lotw = 0
    confirmed_qrz = 0

    for row in local_qsos:
        qso_id, call, qso_date, time_on, band = row
        call = (call or '').upper()
        time_on_short = (time_on or '')[:4]
        band = (band or '').upper()

        key = (call, qso_date, time_on_short, band)

        if key in qrz_lookup:
            qrz_qso = qrz_lookup[key]

            # Extract confirmation fields
            qsl_rcvd = qrz_qso.get('qsl_rcvd', 'N')
            lotw_qsl_rcvd = qrz_qso.get('lotw_qsl_rcvd', '')
            lotw_qslrdate = qrz_qso.get('lotw_qslrdate', '')
            qrzcom_status = qrz_qso.get('qrzcom_qso_upload_status', '')
            app_qrzlog_qsldate = qrz_qso.get('app_qrzlog_qsldate', '')

            # Determine if confirmed
            is_confirmed = (
                qsl_rcvd == 'Y' or
                lotw_qsl_rcvd == 'Y' or
                app_qrzlog_qsldate
            )

            if lotw_qsl_rcvd == 'Y':
                confirmed_lotw += 1
            if app_qrzlog_qsldate:
                confirmed_qrz += 1

            # Update local record
            cursor.execute("""
                UPDATE qsos SET
                    qsl_rcvd = ?,
                    lotw_qsl_rcvd = ?,
                    lotw_qslrdate = ?,
                    qrzcom_qso_upload_status = ?,
                    app_qrzlog_qsldate = ?
                WHERE id = ?
            """, (
                'Y' if is_confirmed else qsl_rcvd,
                lotw_qsl_rcvd,
                lotw_qslrdate,
                qrzcom_status,
                app_qrzlog_qsldate,
                qso_id
            ))

            if cursor.rowcount > 0:
                updated += 1

    conn.commit()
    conn.close()

    return updated, confirmed_lotw, confirmed_qrz


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'logbook.db'

    # Get API key
    api_key = get_api_key()
    if not api_key:
        print("Error: QRZ API key not found.")
        print()
        print("Please set your QRZ API key using one of these methods:")
        print()
        print("1. Environment variable:")
        print("   export QRZ_API_KEY='your-api-key-here'")
        print()
        print("2. Create a .env file in this directory with:")
        print("   QRZ_API_KEY=your-api-key-here")
        print()
        print("To get your API key:")
        print("  1. Log in to QRZ.com")
        print("  2. Go to 'Settings' (under your callsign menu)")
        print("  3. Click 'QRZ Logbook Settings'")
        print("  4. Your API key is shown under 'API Access'")
        print("     (You may need to enable API access first)")
        sys.exit(1)

    print(f"Using database: {db_path}")
    print()

    # Fetch QSOs from QRZ
    try:
        qrz_qsos = fetch_qrz_logbook(api_key)
    except Exception as e:
        print(f"Error fetching from QRZ: {e}")
        sys.exit(1)

    if not qrz_qsos:
        print("No QSOs found in QRZ logbook.")
        sys.exit(0)

    # Update local database
    print()
    print("Updating local database with confirmation status...")
    updated, lotw_confirmed, qrz_confirmed = update_confirmations(db_path, qrz_qsos)

    print()
    print(f"Updated {updated} QSO records")
    print(f"  LoTW confirmed: {lotw_confirmed}")
    print(f"  QRZ confirmed: {qrz_confirmed}")
    print()
    print("Done! Run qso_graph.py to regenerate the graph.")


if __name__ == '__main__':
    main()
