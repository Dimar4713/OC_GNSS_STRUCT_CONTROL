from math import isclose, pi

import pytest

from constellation_control.adapters.iac_gnss_tables import IacDataset, parse_iac_json
from constellation_control.adapters.iac_gps_beidou_almanac import (
    normalize_iac_beidou_almanac,
    normalize_iac_gps_almanac,
)


def test_iac_gps_source_declared_units_are_explicit() -> None:
    table = parse_iac_json(
        IacDataset.GPS_ALMANAC,
        '[{"PRN":"01","datetime":"09.08.26","t":"61440","e":"0,00186","i":"54,83668","DomegaDT":"-4,59040E-7","A":"26559,08565","Lomega":"14,57309","w":"9,86332","mm":"7,59378","af0":"2,01225E-4","af1":"-1,09139E-11"}]',
    )
    record = normalize_iac_gps_almanac(table).records[0]
    assert record.prn == 1
    assert record.base_date_utc.isoformat() == "2026-08-09"
    assert record.epoch_utc.isoformat() == "2026-08-09T17:04:00+00:00"
    assert isclose(record.semi_major_axis_km, 26559.08565)
    assert isclose(record.semi_major_axis_m, 26_559_085.65)
    assert isclose(record.inclination_rad, 54.83668 * pi / 180.0)
    assert isclose(record.raan_rate_rad_s, -4.59040e-7 * pi / 180.0)


def test_iac_beidou_source_declared_units_are_explicit() -> None:
    table = parse_iac_json(
        IacDataset.BEIDOU_ALMANAC,
        '["26.08.26",{"ID":"01","Health":"000","Eccentricity":0.00055980682373,"Time of Applicability(s)":16384,"Orbital Inclination(rad)":0.0074242273,"Rate of Right Ascen(r/s)":1.63435379e-09,"SQRT(A)  (m 1/2)":6493.561035,"Right Ascen at Week(rad)":0.390737039,"Argument of Perigee(rad)":-3.013041993,"Mean Anom(rad)":-0.022596631,"Af0(s)":-9.536743e-07,"Af1(s/s)":0,"week":1077}]',
    )
    record = normalize_iac_beidou_almanac(table).records[0]
    assert record.prn == 1
    assert record.health_code == "000"
    assert isclose(record.inclination_rad, 0.0074242273)
    assert isclose(record.raan_rate_rad_s, 1.63435379e-09)
    assert isclose(record.sqrt_a_source, 6493.561035)
    assert isclose(record.semi_major_axis_m_from_sqrt_a, 6493.561035**2)
    assert record.week == 1077


def test_iac_gps_missing_source_column_fails_closed() -> None:
    table = parse_iac_json(
        IacDataset.GPS_ALMANAC,
        '[{"PRN":"01","datetime":"09.08.26","t":"61440","e":"0,00186","i":"54,83668","DomegaDT":"-4,59040E-7","A":"26559,08565","Lomega":"14,57309","w":"9,86332","mm":"7,59378","af0":"2,01225E-4","af1":"-1,09139E-11"}]',
    )
    bad = table.__class__(dataset=table.dataset, source_url=table.source_url, source_sha256=table.source_sha256, headers=table.headers[:-1], rows=tuple(row[:-1] for row in table.rows), canonical_tsv="x")
    with pytest.raises(ValueError, match="missing columns"):
        normalize_iac_gps_almanac(bad)
