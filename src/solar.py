from datetime import date
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun


# Calculates sunrise and sunset for a given date and geographic location.
def get_sun_times(
    target_date: date,
    latitude: float,
    longitude: float,
    timezone: str,
):
    # Create the location Astral uses for its solar calculations.
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