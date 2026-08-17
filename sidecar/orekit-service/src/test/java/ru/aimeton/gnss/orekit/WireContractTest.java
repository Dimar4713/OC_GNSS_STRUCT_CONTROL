package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.util.List;

import org.junit.jupiter.api.Test;

final class WireContractTest {

    @Test
    void cartesianVelocityUsesCanonicalPythonWireName() throws Exception {
        var mapper = OrekitServiceMain.mapper();
        OsculatingState state = new OsculatingState(
                0.0,
                List.of(1.0, 2.0, 3.0),
                List.of(4.0, 5.0, 6.0));

        String json = mapper.writeValueAsString(state);
        assertTrue(json.contains("\"v_m_s\""));
        assertFalse(json.contains("\"v_ms\""));

        OsculatingState restored = mapper.readValue(json, OsculatingState.class);
        assertEquals(state, restored);
    }

    @Test
    void maneuverDeltaVUsesCanonicalPythonWireName() throws Exception {
        var mapper = OrekitServiceMain.mapper();
        Maneuver maneuver = new Maneuver(
                "SYNTH-1",
                0.0,
                List.of(0.1, 0.2, 0.3));

        String json = mapper.writeValueAsString(maneuver);
        assertTrue(json.contains("\"dv_rtn_m_s\""));
        assertFalse(json.contains("\"dv_rtn_ms\""));

        Maneuver restored = mapper.readValue(json, Maneuver.class);
        assertEquals(maneuver, restored);
    }
}
