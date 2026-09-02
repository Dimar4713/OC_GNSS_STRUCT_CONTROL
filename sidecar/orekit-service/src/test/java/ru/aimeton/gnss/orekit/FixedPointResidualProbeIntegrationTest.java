package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Path;
import java.util.List;

import org.hipparchus.ode.nonstiff.DormandPrince853Integrator;
import org.hipparchus.util.MathUtils;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.orekit.attitudes.AttitudeProvider;
import org.orekit.attitudes.LofOffset;
import org.orekit.forces.gravity.HolmesFeatherstoneAttractionModel;
import org.orekit.forces.gravity.potential.NormalizedSphericalHarmonicsProvider;
import org.orekit.forces.gravity.potential.UnnormalizedSphericalHarmonicsProvider;
import org.orekit.frames.Frame;
import org.orekit.frames.LOFType;
import org.orekit.orbits.EquinoctialOrbit;
import org.orekit.orbits.PositionAngleType;
import org.orekit.propagation.SpacecraftState;
import org.orekit.propagation.numerical.NumericalPropagator;
import org.orekit.propagation.semianalytical.dsst.DSSTPropagator;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTForceModel;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTZonal;
import org.orekit.time.AbsoluteDate;

/** Evidence-only diagnostics for issue #186. Not part of runtime authority. */
final class FixedPointResidualProbeIntegrationTest {
    private static final double MU = 398600441800000.0;
    private static final double STEP_S = 30.0;
    private static final double INITIAL_MASS_KG = 550.0;
    private static final double DSST_LV_THRESHOLD = Math.PI * 1.0e-13;
    private static OrekitRuntime runtime;

    @BeforeAll
    static void setUpRuntime() throws Exception {
        String dataPath = System.getenv("OREKIT_DATA_PATH");
        if (dataPath == null || dataPath.isBlank()) {
            throw new IllegalStateException("OREKIT_DATA_PATH is required for Orekit integration tests");
        }
        runtime = new OrekitRuntime(Path.of(dataPath));
        System.setProperty(FixedPointResidualProbe.PROPERTY, "true");
    }

    @Test
    void captureGlo01FixedPointResidualsAtConfirmedFailure() {
        captureFailure(
                "GLO-01",
                -0.6128512204797385,
                -0.16478784655405554,
                2.8463677578328666,
                14_076_060.0);
    }

    @Test
    void captureDependentSatelliteFixedPointResidualsAtConfirmedFailure() {
        captureFailure(
                "GLO-LIN-DEP",
                -0.6126512204797385,
                -0.16478784655405554,
                2.4536686761341424,
                13_265_940.0);
    }

    private static void captureFailure(
            String satelliteId,
            double hx,
            double hy,
            double lambda,
            double failureTimeS) {
        Frame frame = runtime.propagationFrame("EME2000");
        Frame bodyFixed = runtime.bodyFixedFrame();
        AbsoluteDate epoch = runtime.date("2020-01-01T00:00:00Z", "UTC");
        AttitudeProvider attitude = new LofOffset(frame, LOFType.QSW);

        UnnormalizedSphericalHarmonicsProvider unnormalized = runtime.context().getGravityFields()
                .getUnnormalizedProvider(2, 0);
        NormalizedSphericalHarmonicsProvider normalized = runtime.context().getGravityFields()
                .getNormalizedProvider(2, 0);
        List<DSSTForceModel> meanForces = List.of(new DSSTZonal(bodyFixed, unnormalized));

        EquinoctialOrbit initialOrbit = new EquinoctialOrbit(
                25_508_039.165499,
                0.0,
                0.0,
                hx,
                hy,
                lambda,
                PositionAngleType.MEAN,
                frame,
                epoch,
                MU);
        SpacecraftState initialMean = new SpacecraftState(initialOrbit).withMass(INITIAL_MASS_KG);
        SpacecraftState initialOsculating = DSSTPropagator.computeOsculatingState(initialMean, attitude, meanForces);

        DormandPrince853Integrator integrator = new DormandPrince853Integrator(0.1, 120.0, 1.0e-6, 1.0e-12);
        NumericalPropagator propagator = new NumericalPropagator(integrator, attitude);
        propagator.setInitialState(initialOsculating);
        propagator.addForceModel(new HolmesFeatherstoneAttractionModel(bodyFixed, normalized));

        SpacecraftState osculating = initialOsculating;
        for (double timeS = 0.0; timeS <= failureTimeS; timeS += STEP_S) {
            osculating = propagator.propagate(epoch.shiftedBy(timeS));
            if (timeS < failureTimeS) {
                DSSTPropagator.computeMeanState(osculating, attitude, meanForces);
            }
        }

        SpacecraftState failingOsculating = osculating;
        assertThrows(
                RuntimeException.class,
                () -> DSSTPropagator.computeMeanState(failingOsculating, attitude, meanForces));
        FixedPointResidualProbe.logFailure(
                satelliteId,
                failureTimeS,
                failingOsculating.getOrbit(),
                attitude,
                meanForces,
                failingOsculating.getMass());

        EquinoctialOrbit failingEquinoctial = new EquinoctialOrbit(failingOsculating.getOrbit());
        double originalLv = failingEquinoctial.getLv();
        double lvUlp = Math.ulp(originalLv);
        assertTrue(
                lvUlp > DSST_LV_THRESHOLD,
                () -> "confirmed failure requires lv ULP above DSST threshold: lv=" + originalLv
                        + " ulp=" + lvUlp + " threshold=" + DSST_LV_THRESHOLD);

        double normalizedLv = MathUtils.normalizeAngle(originalLv, 0.0);
        EquinoctialOrbit normalizedOrbit = new EquinoctialOrbit(
                failingEquinoctial.getA(),
                failingEquinoctial.getEquinoctialEx(),
                failingEquinoctial.getEquinoctialEy(),
                failingEquinoctial.getHx(),
                failingEquinoctial.getHy(),
                normalizedLv,
                PositionAngleType.TRUE,
                failingEquinoctial.getFrame(),
                failingEquinoctial.getDate(),
                failingEquinoctial.getMu());
        SpacecraftState normalizedState = new SpacecraftState(normalizedOrbit, failingOsculating.getAttitude())
                .withMass(failingOsculating.getMass());

        assertTrue(
                Math.ulp(normalizedLv) < DSST_LV_THRESHOLD,
                () -> "normalized lv must restore double resolution margin: lv=" + normalizedLv
                        + " ulp=" + Math.ulp(normalizedLv) + " threshold=" + DSST_LV_THRESHOLD);
        assertDoesNotThrow(
                () -> DSSTPropagator.computeMeanState(normalizedState, attitude, meanForces),
                "angle-normalized but physically equivalent state should converge below the longitude ULP floor");
    }
}
