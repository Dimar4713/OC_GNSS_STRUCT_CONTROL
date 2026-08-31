package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.nio.file.Path;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

final class GlonassAlmanacMeanConversionEngineIntegrationTest {
    private static GlonassAlmanacMeanConversionEngine engine;

    @BeforeAll
    static void setUpRuntime() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }
        engine = new GlonassAlmanacMeanConversionEngine(new OrekitRuntime(Path.of(dataPath)));
    }

    @Test
    void convertsExplicitGlonassAlmanacThroughAnalyticalPropagatorAndDsstMean() {
        MeanConversionResult result = engine.convert(request(0));
        assertEquals("GLONASS-ALMANAC-OREKIT-ANALYTICAL", result.backendMetadata().get("source_authority"));
        assertEquals("glonass-labelled-authority-v1", result.backendMetadata().get("almanac_source_format"));
        assertEquals("1", result.backendMetadata().get("glonass_slot"));
        assertTrue(result.backendMetadata().get("conversion_chain").contains("Orekit-GLONASSAnalyticalPropagator"));
        assertEquals("orekit-dsst-13.1.7-from-osculating", result.meanOrbit().definition().theory());
        assertEquals("glonass-almanac-authority-test-fingerprint", result.meanOrbit().definition().forceModelFingerprint());
        assertTrue(Double.isFinite(result.meanOrbit().aM()));
        assertTrue(result.meanOrbit().aM() > 0.0);
    }

    @Test
    void rejectsOutOfRangeFrequencyChannel() {
        IllegalArgumentException error = assertThrows(IllegalArgumentException.class, () -> engine.convert(request(7)));
        assertTrue(error.getMessage().contains("frequency channel"));
    }

    private static GlonassAlmanacToMeanRequest request(int frequencyChannel) {
        SpacecraftModel spacecraft = new SpacecraftModel(500.0, 50.0, 220.0, 8.0, 1.3);
        ForceModel forceModel = new ForceModel(
                "design", OrekitRuntime.GRAVITY_MODEL, 3.986004418e14, 6_378_137.0,
                1.0 / 298.257223563, 0.00108262668, 7.2921150e-5, 8, 8,
                true, true, true, false, false);
        return new GlonassAlmanacToMeanRequest(
                "glo-authority.txt", 1, frequencyChannel, 0, "2026-01-01", 3600.0,
                1.0, 0.001, 0.5, 0.001, 0.0, 0.0, 0.0, 0.0, 0.0,
                "EME2000", "2026-01-01T01:00:00Z", "UTC",
                spacecraft, forceModel, "glonass-almanac-authority-test-fingerprint");
    }
}
