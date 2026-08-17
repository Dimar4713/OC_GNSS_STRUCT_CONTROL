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
}
