#!/usr/bin/env python3
"""Generate a graph of QSOs over time, showing confirmed vs unconfirmed."""

import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def main():
    conn = sqlite3.connect('logbook.db')
    cursor = conn.cursor()

    # Get QSOs grouped by date with confirmation status
    # Check for confirmations from: qsl_rcvd, lotw_qsl_rcvd, or app_qrzlog_qsldate
    cursor.execute("""
        SELECT qso_date,
               SUM(CASE WHEN qsl_rcvd = 'Y'
                        OR lotw_qsl_rcvd = 'Y'
                        OR (app_qrzlog_qsldate IS NOT NULL AND app_qrzlog_qsldate != '')
                   THEN 1 ELSE 0 END) as confirmed,
               SUM(CASE WHEN NOT (qsl_rcvd = 'Y'
                                  OR lotw_qsl_rcvd = 'Y'
                                  OR (app_qrzlog_qsldate IS NOT NULL AND app_qrzlog_qsldate != ''))
                   THEN 1 ELSE 0 END) as unconfirmed
        FROM qsos
        GROUP BY qso_date
        ORDER BY qso_date
    """)

    rows = cursor.fetchall()

    # Get confirmed DXCC entities with their earliest confirmation date
    # We want the first date each DXCC entity was confirmed
    cursor.execute("""
        SELECT dxcc, MIN(qso_date) as first_confirmed_date
        FROM qsos
        WHERE dxcc IS NOT NULL
          AND dxcc != ''
          AND (qsl_rcvd = 'Y'
               OR lotw_qsl_rcvd = 'Y'
               OR (app_qrzlog_qsldate IS NOT NULL AND app_qrzlog_qsldate != ''))
        GROUP BY dxcc
        ORDER BY first_confirmed_date
    """)

    dxcc_rows = cursor.fetchall()
    conn.close()

    # Build a map of date -> number of new DXCC entities confirmed that day
    dxcc_by_date = {}
    for dxcc, first_date in dxcc_rows:
        dxcc_by_date[first_date] = dxcc_by_date.get(first_date, 0) + 1

    if not rows:
        print("No QSOs found in database.")
        return

    # Parse dates and calculate cumulative totals
    dates = []
    cumulative_confirmed = []
    cumulative_total = []
    cumulative_dxcc = []

    running_confirmed = 0
    running_total = 0
    running_dxcc = 0

    for row in rows:
        date_str, confirmed, unconfirmed = row
        date = datetime.strptime(date_str, "%Y%m%d")
        dates.append(date)

        running_confirmed += confirmed
        running_total += confirmed + unconfirmed
        running_dxcc += dxcc_by_date.get(date_str, 0)

        cumulative_confirmed.append(running_confirmed)
        cumulative_total.append(running_total)
        cumulative_dxcc.append(running_dxcc)

    # Create the plot with secondary y-axis for DXCC entities
    fig, ax = plt.subplots(figsize=(12, 6))
    ax2 = ax.twinx()

    # Plot total QSOs
    ax.fill_between(dates, cumulative_total, alpha=0.3, color='blue', label='Total QSOs')
    ax.plot(dates, cumulative_total, color='blue', linewidth=2)

    # Plot confirmed QSOs
    if running_confirmed > 0:
        ax.fill_between(dates, cumulative_confirmed, alpha=0.5, color='green', label='Confirmed QSOs')
        ax.plot(dates, cumulative_confirmed, color='green', linewidth=2)

    # Plot confirmed DXCC entities on secondary axis
    if running_dxcc > 0:
        ax2.plot(dates, cumulative_dxcc, color='purple', linewidth=2, linestyle='--', label='Confirmed DX Entities')
        ax2.set_ylabel('Confirmed DX Entities', fontsize=12, color='purple')
        ax2.tick_params(axis='y', labelcolor='purple')

    # Formatting
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Cumulative QSOs', fontsize=12)
    ax.set_title('QSO Log Progress Over Time', fontsize=14, fontweight='bold')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=45, ha='right')

    # Combine legends from both axes
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
    ax.grid(True, alpha=0.3)

    # Add stats annotation
    stats_text = f"Total QSOs: {running_total}\nConfirmed: {running_confirmed} ({100*running_confirmed/running_total:.1f}%)\nDX Entities: {running_dxcc}"
    ax.annotate(stats_text, xy=(0.98, 0.02), xycoords='axes fraction',
                ha='right', va='bottom', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig('qso_graph.png', dpi=150)
    print(f"Graph saved to qso_graph.png")
    print(f"Total QSOs: {running_total}")
    print(f"Confirmed QSOs: {running_confirmed}")
    print(f"Confirmed DX Entities: {running_dxcc}")

if __name__ == "__main__":
    main()
