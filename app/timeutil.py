"""Display time zone. Every timestamp is STORED as naive UTC; people see and type times in the site's zone (IST by default).

A fixed offset is used instead of a zone database, because IST has no daylight saving and Windows has no tz database by default.
Change APP_TZ_NAME / APP_TZ_OFFSET_MINUTES for another fixed-offset zone.
"""
from datetime import timedelta

from flask import current_app
from wtforms.fields import DateTimeLocalField


def offset():
    return timedelta(minutes=current_app.config["TZ_OFFSET_MINUTES"])


def tz_name():
    return current_app.config["TZ_NAME"]


def to_local(dt):
    return dt + offset() if dt else dt


def from_local(dt):
    return dt - offset() if dt else dt


def fmt(dt, pattern="%d %b %Y %H:%M"):
    return f"{to_local(dt).strftime(pattern)} {tz_name()}" if dt else ""


class LocalDateTimeField(DateTimeLocalField):
    """A datetime-local input that the user fills in site time; `.data` is always naive UTC, like every other timestamp here."""

    def process_formdata(self, valuelist):
        super().process_formdata(valuelist)
        if self.data:
            self.data = from_local(self.data)

    def _value(self):
        if self.raw_data:
            return " ".join(self.raw_data)
        if not self.data:
            return ""
        pattern = self.format[0] if isinstance(self.format, (list, tuple)) else self.format
        return to_local(self.data).strftime(pattern)
