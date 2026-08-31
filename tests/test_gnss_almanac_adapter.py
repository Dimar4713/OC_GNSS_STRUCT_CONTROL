from __future__ import annotations

from math import isclose, pi

import pytest

from constellation_control.adapters.gnss_almanac import (
    GnssAlmanacFormat,
    GpsSemRecord,
    GpsYumaRecord,
    GlonassAlmanacRecord,
    preview_gnss_almanac,
)


YUMA = """
******** Week 2234 almanac for PRN-01 ********
ID:                         1
Health:                     000
Eccentricity:               0.0123456789
Time of Applicability(s):  589824.0
Orbital Inclination(rad):   0.9599310886
Rate of Right Ascen(r/s):  -8.0E-09
SQRT(A)  (m 1/2):          5153.65234375
Right Ascen at Week(rad):   1.2345
Argument of Perigee(rad):   0.4567
Mean Anom(rad):             2.3456
Af0(s):                     1.0E-04
Af1(s/s):                   2.0E-12
week:                       2234
"""


SEM = """
1 CURRENT.AL3
2234 589824
1
80
1
0.0123456789 0.005  -8.0E-09
5153.65234375 0.392858 0.145372
0.746638 1.0E-04 2.0E-12
0
9
"""


GLONASS = """
Slot: 1
Frequency Channel: -7
Health: 0
Reference Day: 100
Reference Time(s): 43200
Lambda(rad): 1.2
Delta I(rad): 0.01
Eccentricity: 0.001
Argument of Perigee(rad): 0.7
Draconian Period(s): 40544
Draconian Period Rate(s/orbit): -0.01
"""


def test_yuma_is_typed_as_reduced_precision_almanac_and_not_runnable() -> None:
    preview = preview_gnss_almanac("current.alm", YUMA, GnssAlmanacFormat.GPS_YUMA)
    assert preview.source_format == GnssAlmanacFormat.GPS_YUMA
    assert preview.runnable_promotion_allowed is False
    assert len(preview.source_sha256) == 64
    record = preview.records[0]
    assert isinstance(record, GpsYumaRecord)
    assert record.prn == 1
    assert isclose(record.inclination_rad, 0.9599310886)
    assert "radians" in preview.units_note


def test_sem_keeps_semicircle_semantics_and_inclination_offset() -> None:
    preview = preview_gnss_almanac("current.al3", SEM, GnssAlmanacFormat.GPS_SEM)
    assert preview.runnable_promotion_allowed is False
    record = preview.records[0]
    assert isinstance(record, GpsSemRecord)
    assert record.gps_week == 2234
    assert isclose(record.inclination_offset_semicircles, 0.005)
    assert isclose(record.inclination_rad, 0.305 * pi)
    assert "semicircles" in preview.units_note


def test_sem_rejects_wrong_record_line_count() -> None:
    with pytest.raises(ValueError, match="SEM expected"):
        preview_gnss_almanac("broken.al3", SEM.rsplit("\n", 3)[0], GnssAlmanacFormat.GPS_SEM)


def test_duplicate_yuma_prn_fails_closed() -> None:
    duplicate = YUMA + "\n" + YUMA
    with pytest.raises(ValueError, match="duplicate satellite identifiers"):
        preview_gnss_almanac("dup.alm", duplicate, GnssAlmanacFormat.GPS_YUMA)


def test_glonass_labelled_text_is_explicit_interchange_not_raw_decoder() -> None:
    preview = preview_gnss_almanac("glo.txt", GLONASS, GnssAlmanacFormat.GLONASS_TEXT)
    record = preview.records[0]
    assert isinstance(record, GlonassAlmanacRecord)
    assert record.slot == 1
    assert record.frequency_channel == -7
    assert preview.runnable_promotion_allowed is False
    assert "does not decode raw GLONASS navigation strings" in preview.units_note
