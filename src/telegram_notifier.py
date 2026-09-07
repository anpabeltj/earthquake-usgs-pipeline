"""
Send Telegram alerts for newly recorded earthquakes.

Runs as the last task in the operational DAG, after gold is rebuilt.

Not every earthquake is worth a message. At magnitude 4.5 and above the
catalog records roughly fourteen events a day worldwide, most of them
far out at sea with no effect on anyone. Only events that clear one of
the thresholds below are announced.

Which ones have already gone out is tracked in a log table rather than
by comparing timestamps, so a retried task never sends the same alert
twice.
"""

import logging
import os

from datetime import datetime, timedelta, timezone
import requests
from google.cloud import bigquery

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GOLD_DATASET = os.getenv("BQ_GOLD_DATASET", "gold")
OPS_DATASET = os.getenv("BQ_OPS_DATASET", "ops")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# An event is announced if it meets any one of these.
ALERT_MIN_MAGNITUDE = float(os.getenv("ALERT_MIN_MAGNITUDE", "6.0"))
ALERT_ON_TSUNAMI = True
ALERT_ON_PAGER_LEVELS = ("orange", "red")

# Nothing older than this is announced, so the first run after an outage
# does not fire off a burst of alerts about old news. gold_fact_earthquake
# only stores event_date, not the full event_time, so this is a date
# lookback rather than an hour count.
MAX_AGE_DAYS = 1

REQUEST_TIMEOUT_SECONDS = 15

logger = logging.getLogger(__name__)


def find_events_to_announce(client):
    """Return events that clear a threshold and have not been sent yet."""
    pager_levels = ", ".join(f"'{level}'" for level in ALERT_ON_PAGER_LEVELS)
    tsunami_clause = "or fact.tsunami_flag = 1" if ALERT_ON_TSUNAMI else ""

    sql = f"""
        select
            fact.usgs_id,
            fact.event_time,
            fact.magnitude,
            fact.depth_km,
            fact.tsunami_flag,
            fact.felt_reports,
            location.nearest_place,
            location.region,
            location.country,
            magnitude_cat.magnitude_category,
            depth_cat.depth_category,
            alert_lvl.alert_level
        from `{PROJECT_ID}.{GOLD_DATASET}.gold_fact_earthquake` as fact
        inner join `{PROJECT_ID}.{GOLD_DATASET}.gold_dim_location` as location
            using (location_id)
        inner join `{PROJECT_ID}.{GOLD_DATASET}.gold_dim_magnitude_category` as magnitude_cat
            using (magnitude_category_id)
        inner join `{PROJECT_ID}.{GOLD_DATASET}.gold_dim_depth_category` as depth_cat
            using (depth_category_id)
        inner join `{PROJECT_ID}.{GOLD_DATASET}.gold_dim_alert_level` as alert_lvl
            using (alert_level_id)
        left join `{PROJECT_ID}.{OPS_DATASET}.notification_log` as log
            on fact.usgs_id = log.usgs_id
        where log.usgs_id is null
        and fact.event_date >= date_sub(current_date(), interval {MAX_AGE_DAYS} day)
          and (
                fact.magnitude >= {ALERT_MIN_MAGNITUDE}
             {tsunami_clause}
             or alert_lvl.alert_level in ({pager_levels})
          )
        order by fact.event_time
    """

    return list(client.query(sql).result())


def format_delay(event_time):
    """
    How long ago the event happened, in plain words.

    The gap between an earthquake and its alert is worth showing. Most
    of it is USGS review time, not pipeline latency: the catalog only
    publishes an event once its solution is good enough, and the
    pipeline then picks it up on the next hourly run.
    """
    delta = datetime.now(timezone.utc) - event_time
    minutes = int(delta.total_seconds() // 60)

    if minutes < 60:
        return f"{minutes} min ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m ago"

    days = hours // 24
    return f"{days}d {hours % 24}h ago"


def build_message(row):
    """Format one earthquake as a Telegram message."""
    if row.tsunami_flag == 1:
        header = "TSUNAMI FLAGGED - EARTHQUAKE ALERT"
    elif row.alert_level in ALERT_ON_PAGER_LEVELS:
        header = f"HIGH IMPACT EARTHQUAKE - PAGER {row.alert_level.upper()}"
    else:
        header = "Major earthquake recorded"

    location_parts = []
    if row.nearest_place:
        location_parts.append(row.nearest_place)
    if row.region and row.region != row.nearest_place:
        location_parts.append(row.region)
    location_text = ", ".join(location_parts) if location_parts else "unknown location"

    lines = [
        header,
        "",
        f"Magnitude: {row.magnitude} ({row.magnitude_category})",
        f"Depth: {row.depth_km} km ({row.depth_category})",
        f"Location: {location_text}",
    ]

    if row.country:
        lines.append(f"Country: {row.country}")

    local_time = row.event_time.astimezone(timezone(timedelta(hours=7)))
    lines.append(
        f"Occurred: {local_time:%d %b %Y, %H:%M} WIB "
        f"({row.event_time:%H:%M} UTC) — {format_delay(row.event_time)}"
    )

    if row.felt_reports:
        lines.append(f"Felt reports: {row.felt_reports}")

    lines.append("")
    lines.append("Source: USGS Earthquake Catalog")

    return "\n".join(lines)


def send_to_telegram(message):
    """Post one message to the configured Telegram chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}

    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()


def record_as_notified(client, usgs_id):
    """Log one event so it is never announced again."""
    table_id = f"{PROJECT_ID}.{OPS_DATASET}.notification_log"
    errors = client.insert_rows_json(table_id, [{"usgs_id": usgs_id}])

    if errors:
        raise RuntimeError(f"failed to write notification log: {errors}")


def send_new_earthquake_alerts():
    """
    Announce anything new. This is the function Airflow calls.

    Each event is logged immediately after its message is sent, so a
    failure halfway through leaves the sent ones logged and only the
    remainder goes out on the next run.
    """
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set")

    client = bigquery.Client(project=PROJECT_ID)
    events = find_events_to_announce(client)

    if not events:
        logger.info("nothing new to announce")
        return 0

    logger.info("announcing %s events", len(events))

    sent = 0
    for row in events:
        send_to_telegram(build_message(row))
        record_as_notified(client, row.usgs_id)
        sent = sent + 1
        logger.info("announced %s", row.usgs_id)

    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_new_earthquake_alerts()
