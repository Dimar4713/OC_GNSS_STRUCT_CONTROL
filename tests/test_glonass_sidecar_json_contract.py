from pathlib import Path


def test_glonass_python_client_uses_java_sidecar_json_field_names() -> None:
    source = Path("src/constellation_control/adapters/orekit/mean_conversion.py").read_text(encoding="utf-8")
    block = source.split("class OrekitGlonassAlmanacMeanConversionClient:", 1)[1]

    assert '"delta_irad": delta_i_rad' in block
    assert '"delta_ts": delta_t_s' in block
    assert '"delta_tdot": delta_t_dot' in block

    assert '"delta_i_rad": delta_i_rad' not in block
    assert '"delta_t_s": delta_t_s' not in block
    assert '"delta_t_dot": delta_t_dot' not in block
