package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

final class PropagationProgressObserverIntegrationTest {
    private static PropagationEngine engine;

    @BeforeAll
    static void setUpRuntime() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }
        engine = new PropagationEngine(new OrekitRuntime(Path.of(dataPath)));
    }

    @Test
    void validationReportsExactNumericalAndMeanConversionPhases() {
        List<PropagationEngine.ProgressEvent> events = new ArrayList<>();

        engine.propagate(validationRequest(), events::add);

        assertEquals(4, events.size());
        assertEvent(events.get(0), "numerical_propagation", 1, 2, 0.0);
        assertEvent(events.get(1), "osculating_to_mean", 1, 2, 0.0);
        assertEvent(events.get(2), "numerical_propagation", 2, 2, 300.0);
        assertEvent(events.get(3), "osculating_to_mean", 2, 2, 300.0);
        assertTrue(events.stream().allMatch(event -> event.epoch() != null && !event.epoch().isBlank()));
    }

    private static void assertEvent(
            PropagationEngine.ProgressEvent event,
            String phase,
            int pointIndex,
            int pointTotal,
            double timeS) {
        assertEquals(phase, event.phase());
        assertEquals("SYNTH-PROGRESS", event.satelliteId());
        assertEquals(1, event.satelliteIndex());
        assertEquals(1, event.satelliteTotal());
        assertEquals(pointIndex, event.pointIndex());
        assertEquals(pointTotal, event.pointTotal());
        assertEquals(timeS, event.timeS());
    }

    private static PropagationRequest validationRequest() {
        String fingerprint = "progress-observer-force-model-sha256";
        MeanElementDefinition definition = new MeanElementDefinition(
                "equinoctial", "progress-observer-input", fingerprint);
        MeanOrbit orbit = new MeanOrbit(26_560_000.0, 0.001, 0.0, 0.2, 0.0, 0.3, definition);
        SpacecraftModel spacecraft = new SpacecraftModel(500.0, 50.0, 220.0, 8.0, 1.3);
        SatelliteSpec satellite = new SatelliteSpec(
                "SYNTH-PROGRESS", "P-SYNTH", "reference", null, orbit, spacecraft);
        ForceModel forceModel = new ForceModel(
                "validation",
                OrekitRuntime.GRAVITY_MODEL,
                3.986004418e14,
                6_378_137.0,
                1.0 / 298.257223563,
                0.00108262668,
                7.2921150e-5,
                2,
                0,
                false,
                false,
                false,
                false,
                false);
        Integrator integrator = new Integrator(0.1, 60.0, 1.0e-6, 1.0e-12);
        return new PropagationRequest(
                "progress-observer-integration",
                "2026-01-01T00:00:00Z",
                "EME2000",
                "UTC",
                List.of(satellite),
                List.of(),
                300.0,
                300.0,
                forceModel,
                integrator,
                4713,
                fingerprint);
    }
}
