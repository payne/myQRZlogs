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
    conn.close()

    if not rows:
        print("No QSOs found in database.")
        return

    # Parse dates and calculate cumulative totals
    dates = []
    cumulative_confirmed = []
    cumulative_total = []

    running_confirmed = 0
    running_total = 0

    for row in rows:
        date_str, confirmed, unconfirmed = row
        date = datetime.strptime(date_str, "%Y%m%d")
        dates.append(date)

        running_confirmed += confirmed
        running_total += confirmed + unconfirmed

        cumulative_confirmed.append(running_confirmed)
        cumulative_total.append(running_total)

    # Create the plot
    fig, ax = plt.subplots(figsize=(12, 6))

    # Plot total QSOs
    ax.fill_between(dates, cumulative_total, alpha=0.3, color='blue', label='Total QSOs')
    ax.plot(dates, cumulative_total, color='blue', linewidth=2)

    # Plot confirmed QSOs
    if running_confirmed > 0:
        ax.fill_between(dates, cumulative_confirmed, alpha=0.5, color='green', label='Confirmed QSOs')
        ax.plot(dates, cumulative_confirmed, color='green', linewidth=2)

    # Formatting
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Cumulative QSOs', fontsize=12)
    ax.set_title('QSO Log Progress Over Time', fontsize=14, fontweight='bold')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=45, ha='right')

    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    # Add stats annotation
    stats_text = f"Total QSOs: {running_total}\nConfirmed: {running_confirmed} ({100*running_confirmed/running_total:.1f}%)"
    ax.annotate(stats_text, xy=(0.98, 0.02), xycoords='axes fraction',
                ha='right', va='bottom', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig('qso_graph.png', dpi=150)
    print(f"Graph saved to qso_graph.png")
    print(f"Total QSOs: {running_total}")
    print(f"Confirmed QSOs: {running_confirmed}")

if __name__ == "__main__":
    main()
