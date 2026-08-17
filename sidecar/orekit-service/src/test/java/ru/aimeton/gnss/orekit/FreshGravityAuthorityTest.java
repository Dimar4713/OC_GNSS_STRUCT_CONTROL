package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Path;

import org.junit.jupiter.api.Test;

final class FreshGravityAuthorityTest {

    @Test
    void cleanRuntimeReportsEightByEightGravityIdentity() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }

        OrekitRuntime fresh = new OrekitRuntime(Path.of(dataPath));
        var provider = fresh.context().getGravityFields().getNormalizedProvider(8, 8);
        System.out.printf(
                "FRESH_GRAVITY_AUTHORITY model=%s degree=8 order=8 mu=%.17e ae=%.17e data_revision=%s data_sha256=%s%n",
                fresh.gravityModel(),
                provider.getMu(),
                provider.getAe(),
                fresh.dataRevision(),
                fresh.dataSha256());

        assertEquals(OrekitRuntime.GRAVITY_MODEL, fresh.gravityModel());
        assertTrue(Math.abs(provider.getMu() - 3.986004418e14) / 3.986004418e14 < 1.0e-8);
        assertTrue(Double.isFinite(provider.getMu()) && provider.getMu() > 0.0);
        assertTrue(Double.isFinite(provider.getAe()) && provider.getAe() > 0.0);
    }
}
