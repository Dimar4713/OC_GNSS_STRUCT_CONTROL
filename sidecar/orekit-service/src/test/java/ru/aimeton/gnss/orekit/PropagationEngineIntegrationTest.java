package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.nio.file.Path;
import java.util.List;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

final class PropagationEngineIntegrationTest {
    private static OrekitRuntime runtime;
    private static PropagationEngine engine;

    @BeforeAll
    static void setUpRuntime() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }
        runtime = new OrekitRuntime(Path.of(dataPath));
        engine = new PropagationEngine(runtime);
    }

    @Test
    void designAndValidationExecuteAgainstPinnedOrekitData() {
        PropagationRequest design = request("design", false, false, false);
        PropagationResult designResult = engine.propagate(design);

        assertEquals("orekit-dsst-design", designResult.backend());
        assertEquals(OrekitRuntime.OREKIT_VERSION, designResult.backendVersion());
        assertEquals(runtime.dataSha256(), designResult.backendMetadata().get("orekit_data_sha256"));
        assertEquals(List.of(0.0, 300.0, 600.0), designResult.timesS());
        assertEquals(3, designResult.meanOrbits().get("SYNTH-1").size());
        assertEquals(3, designResult.cartesianStates().get("SYNTH-1").size());

        PropagationRequest validation = request("validation", false, false, false);
        PropagationResult validationResult = engine.propagate(validation);
        assertEquals("orekit-numerical-validation", validationResult.backend());
        assertEquals(3, validationResult.meanOrbits().get("SYNTH-1").size());
        assertEquals(3, validationResult.cartesianStates().get("SYNTH-1").size());
    }

    @Test
    void meanOsculatingMeanRoundTripUsesTheSameForceModel() {
        PropagationRequest validation = request("validation", false, false, false);
        MeanOrbit expected = validation.satellites().get(0).meanOrbit();
        MeanOrbit actual = engine.propagate(validation).meanOrbits().get("SYNTH-1").get(0);

        assertNear(expected.aM(), actual.aM(), 0.25, "a");
        assertNear(expected.ex(), actual.ex(), 2.0e-10, "ex");
        assertNear(expected.ey(), actual.ey(), 2.0e-10, "ey");
        assertNear(expected.ix(), actual.ix(), 2.0e-10, "ix");
        assertNear(expected.iy(), actual.iy(), 2.0e-10, "iy");
        assertAngleNear(expected.lambdaRad(), actual.lambdaRad(), 2.0e-10, "lambda");
        assertEquals(validation.forceModelFingerprint(), actual.definition().forceModelFingerprint());
    }

    @Test
    void moonSunAndSrpAreExecutableInBothAuthorityModes() {
        PropagationResult design = engine.propagate(request("design", true, true, true));
        PropagationResult validation = engine.propagate(request("validation", true, true, true));

        assertFalse(design.cartesianStates().get("SYNTH-1").isEmpty());
        assertFalse(validation.cartesianStates().get("SYNTH-1").isEmpty());
        assertTrue(design.backendMetadata().get("orekit_data_sha256").length() == 64);
    }

    @Test
    void tesseralGravityExecutesInBothAuthorityModes() {
        PropagationResult design = engine.propagate(
                request("design", false, false, false, List.of(), 2, false));
        PropagationResult validation = engine.propagate(
                request("validation", false, false, false, List.of(), 2, false));

        assertEquals("2", design.backendMetadata().get("gravity_order"));
        assertEquals("2", validation.backendMetadata().get("gravity_order"));
        assertFalse(design.meanOrbits().get("SYNTH-1").isEmpty());
        assertFalse(validation.meanOrbits().get("SYNTH-1").isEmpty());
    }

    @Test
    void relativityExecutesOnlyInNumericalAuthority() {
        PropagationResult validation = engine.propagate(
                request("validation", false, false, false, List.of(), 0, true));
        assertEquals("orekit-numerical-validation", validation.backend());
        assertFalse(validation.cartesianStates().get("SYNTH-1").isEmpty());

        assertThrows(
                UnsupportedOperationException.class,
                () -> engine.propagate(request("design", false, false, false, List.of(), 0, true)));
    }

    @Test
    void positiveTangentialImpulseRaisesMeanSemiMajorAxis() {
        PropagationResult baseline = engine.propagate(request("validation", false, false, false));
        Maneuver maneuver = new Maneuver("SYNTH-1", 0.0, List.of(0.0, 0.1, 0.0));
        PropagationResult maneuvered = engine.propagate(
                request("validation", false, false, false, List.of(maneuver)));

        double baselineA = baseline.meanOrbits().get("SYNTH-1").get(2).aM();
        double maneuveredA = maneuvered.meanOrbits().get("SYNTH-1").get(2).aM();
        assertTrue(
                maneuveredA > baselineA + 100.0,
                () -> "positive QSW/RTN tangential impulse must raise mean a: baseline="
                        + baselineA + " maneuvered=" + maneuveredA);
    }

    private static PropagationRequest request(String mode, boolean moon, boolean sun, boolean srp) {
        return request(mode, moon, sun, srp, List.of(), 0, false);
    }

    private static PropagationRequest request(
            String mode, boolean moon, boolean sun, boolean srp, List<Maneuver> maneuvers) {
        return request(mode, moon, sun, srp, maneuvers, 0, false);
    }

    private static PropagationRequest request(
            String mode,
            boolean moon,
            boolean sun,
            boolean srp,
            List<Maneuver> maneuvers,
            int gravityOrder,
            boolean relativity) {
        String fingerprint = "integration-force-model-sha256";
        MeanElementDefinition definition = new MeanElementDefinition(
                "equinoctial", "synthetic-integration-input", fingerprint);
        MeanOrbit orbit = new MeanOrbit(
                26_560_000.0,
                0.001,
                0.0,
                0.2,
                0.0,
                0.3,
                definition);
        SpacecraftModel spacecraft = new SpacecraftModel(500.0, 50.0, 220.0, 8.0, 1.3);
        SatelliteSpec satellite = new SatelliteSpec("SYNTH-1", "P-SYNTH", "reference", null, orbit, spacecraft);
        ForceModel forceModel = new ForceModel(
                mode,
                3.986004418e14,
                6_378_137.0,
                1.0 / 298.257223563,
                0.00108262668,
                7.2921150e-5,
                2,
                gravityOrder,
                moon,
                sun,
                srp,
                false,
                relativity);
        Integrator integrator = new Integrator(0.1, 60.0, 1.0e-6, 1.0e-12);
        return new PropagationRequest(
                "synthetic-orekit-integration",
                "2026-01-01T00:00:00Z",
                "EME2000",
                "UTC",
                List.of(satellite),
                maneuvers,
                600.0,
                300.0,
                forceModel,
                integrator,
                4713,
                fingerprint);
    }

    private static void assertNear(double expected, double actual, double tolerance, String component) {
        assertTrue(
                Math.abs(expected - actual) <= tolerance,
                () -> component + " round-trip error=" + Math.abs(expected - actual) + " tolerance=" + tolerance);
    }

    private static void assertAngleNear(double expected, double actual, double tolerance, String component) {
        double delta = Math.atan2(Math.sin(actual - expected), Math.cos(actual - expected));
        assertTrue(
                Math.abs(delta) <= tolerance,
                () -> component + " round-trip error=" + Math.abs(delta) + " tolerance=" + tolerance);
    }
}
