package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.nio.file.Path;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

final class MeanConversionEngineIntegrationTest {
    private static MeanConversionEngine engine;

    @BeforeAll
    static void setUpRuntime() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }
        engine = new MeanConversionEngine(new OrekitRuntime(Path.of(dataPath)));
    }

    @Test
    void convertsKeplerianOsculatingInputToForceModelConsistentMeanOrbit() {
        OsculatingToMeanRequest request = request(false);
        MeanConversionResult result = engine.convert(request);

        assertEquals("orekit-dsst-mean-conversion", result.backendMetadata().get("backend"));
        assertEquals(OrekitRuntime.OREKIT_VERSION, result.backendMetadata().get("orekit_version"));
        assertEquals(OrekitRuntime.GRAVITY_MODEL, result.backendMetadata().get("gravity_model"));
        assertEquals("keplerian-osculating", result.backendMetadata().get("input_representation"));
        assertEquals("equinoctial-mean", result.backendMetadata().get("output_representation"));
        assertEquals(request.forceModelFingerprint(), result.meanOrbit().definition().forceModelFingerprint());
        assertEquals("orekit-dsst-13.1.7-from-osculating", result.meanOrbit().definition().theory());
        assertTrue(Double.isFinite(result.meanOrbit().aM()));
        assertTrue(result.meanOrbit().aM() > 0.0);
    }

    @Test
    void rejectsUnsupportedMeanForceConfiguration() {
        UnsupportedOperationException error = assertThrows(
                UnsupportedOperationException.class,
                () -> engine.convert(request(true)));
        assertTrue(error.getMessage().contains("tides=true"));
    }

    private static OsculatingToMeanRequest request(boolean tides) {
        SpacecraftModel spacecraft = new SpacecraftModel(500.0, 50.0, 220.0, 8.0, 1.3);
        ForceModel forceModel = new ForceModel(
                "design",
                OrekitRuntime.GRAVITY_MODEL,
                3.986004418e14,
                6_378_137.0,
                1.0 / 298.257223563,
                0.00108262668,
                7.2921150e-5,
                8,
                8,
                true,
                true,
                true,
                tides,
                false);
        return new OsculatingToMeanRequest(
                "2026-01-01T00:00:00Z",
                "EME2000",
                "UTC",
                26_560_000.0,
                0.001,
                1.13,
                0.2,
                0.4,
                0.6,
                "true",
                spacecraft,
                forceModel,
                "integration-osculating-input-fingerprint");
    }
}
