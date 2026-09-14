"""Shared UTC time helper.
 
Replaces datetime.utcnow(), which is deprecated in Python 3.12+. Critically, it
returns a *naive* UTC datetime (no tzinfo) - the SAME kind utcnow() returned -
because the app's DB columns are naive DateTime and existing code compares and
subtracts against those stored naive values. Returning an aware datetime instead
would raise "can't compare offset-naive and offset-aware datetimes" at those
sites. So this is a drop-in: same value, same naive-ness, just not deprecated.
"""
from datetime import datetime, timezone
 
 
def utcnow() -> datetime:
    """Naive UTC now (drop-in for the deprecated datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
 
