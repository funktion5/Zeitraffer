from datetime import date
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun


def get_sun_times(
    target_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
):
    location = LocationInfo(
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
    )

    sun_times = sun(
        location.observer,
        date=target_date,
        tzinfo=ZoneInfo(timezone),
    )

    return sun_times["sunrise"], sun_times["sunset"]