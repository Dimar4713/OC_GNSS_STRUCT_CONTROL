package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.nio.file.Path;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

final class TleMeanConversionEngineIntegrationTest {
    private static final String LINE1 =
            "1 25544U 98067A   24001.50000000  .00000000  00000-0  00000-0 0  9992";
    private static final String LINE2 =
            "2 25544  51.6400 123.4567 0005000  10.0000 350.0000 15.50000000123456";

    private static TleMeanConversionEngine engine;

    @BeforeAll
    static void setUpRuntime() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }
        engine = new TleMeanConversionEngine(new OrekitRuntime(Path.of(dataPath)));
    }

    @Test
    void convertsTleThroughSgp4TemeAndDsstMeanAuthority() {
        MeanConversionResult result = engine.convert(request(LINE1, LINE2));

        assertEquals("NORAD-TLE-SGP4", result.backendMetadata().get("source_authority"));
        assertEquals("TEME", result.backendMetadata().get("sgp4_frame"));
        assertEquals("25544", result.backendMetadata().get("norad_satellite_number"));
        assertEquals("tle-sgp4-mean-via-osculating-pv", result.backendMetadata().get("input_representation"));
        assertEquals("orekit-dsst-13.1.7-from-osculating", result.meanOrbit().definition().theory());
        assertEquals("tle-authority-test-fingerprint", result.meanOrbit().definition().forceModelFingerprint());
        assertTrue(Double.isFinite(result.meanOrbit().aM()));
        assertTrue(result.meanOrbit().aM() > 0.0);
    }

    @Test
    void rejectsMalformedTleBeforePropagation() {
        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> engine.convert(request(LINE1.substring(0, 68) + "9", LINE2)));
        assertTrue(error.getMessage().contains("format"));
    }

    private static TleToMeanRequest request(String line1, String line2) {
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
                false,
                false);
        return new TleToMeanRequest(
                line1,
                line2,
                "EME2000",
                spacecraft,
                forceModel,
                "tle-authority-test-fingerprint");
    }
}
