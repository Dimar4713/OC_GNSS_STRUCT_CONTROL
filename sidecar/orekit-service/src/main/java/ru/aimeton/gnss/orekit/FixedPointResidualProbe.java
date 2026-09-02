package ru.aimeton.gnss.orekit;

import java.util.Collection;
import java.util.Locale;

import org.hipparchus.geometry.euclidean.threed.Vector3D;
import org.hipparchus.util.FastMath;
import org.hipparchus.util.MathUtils;
import org.orekit.attitudes.AttitudeProvider;
import org.orekit.orbits.EquinoctialOrbit;
import org.orekit.orbits.Orbit;
import org.orekit.orbits.PositionAngleType;
import org.orekit.propagation.SpacecraftState;
import org.orekit.propagation.conversion.osc2mean.DSSTTheory;
import org.orekit.propagation.conversion.osc2mean.FixedPointConverter;
import org.orekit.propagation.conversion.osc2mean.MeanTheory;
import org.orekit.propagation.semianalytical.dsst.DSSTPropagator;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTForceModel;
import org.orekit.utils.TimeStampedPVCoordinates;

/** Diagnostic-only replay of Orekit 13.1.7 FixedPointConverter residuals after an official conversion failure. */
final class FixedPointResidualProbe {
    static final String PROPERTY = "aimeton.dsst.residualDiagnostics";
    private static final double THRESHOLD = 1.0e-13;
    private static final int MAX_ITERATIONS = 200;
    private static final double DAMPING = 1.0;
    private static final double[] DIAGNOSTIC_DAMPINGS = {1.0, 0.9, 0.7, 0.5};

    private FixedPointResidualProbe() {}

    static boolean enabled() {
        return Boolean.getBoolean(PROPERTY);
    }

    static void logFailure(
            String satelliteId,
            double timeS,
            Orbit osculating,
            AttitudeProvider attitudeProvider,
            Collection<DSSTForceModel> forceModels,
            double mass) {
        if (!enabled()) {
            return;
        }

        MeanTheory theory = new DSSTTheory(forceModels, attitudeProvider, mass);
        Orbit equinoctial = theory.preprocessing(osculating);
        double sma = equinoctial.getA();
        double ex = equinoctial.getEquinoctialEx();
        double ey = equinoctial.getEquinoctialEy();
        double hx = equinoctial.getHx();
        double hy = equinoctial.getHy();
        double lv = equinoctial.getLv();

        double thresholdA = THRESHOLD * FastMath.abs(sma);
        double thresholdE = THRESHOLD * (1.0 + FastMath.hypot(ex, ey));
        double thresholdH = THRESHOLD * (1.0 + FastMath.hypot(hx, hy));
        double thresholdLv = THRESHOLD * FastMath.PI;

        Orbit mean = theory.initialize(equinoctial);
        log("START", satelliteId, timeS, 0, sma, ex, ey, hx, hy, lv,
                Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN,
                thresholdA, thresholdE, thresholdH, thresholdLv);

        for (int iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
            Orbit updated = theory.meanToOsculating(mean);
            double deltaA = equinoctial.getA() - updated.getA();
            double deltaEx = equinoctial.getEquinoctialEx() - updated.getEquinoctialEx();
            double deltaEy = equinoctial.getEquinoctialEy() - updated.getEquinoctialEy();
            double deltaHx = equinoctial.getHx() - updated.getHx();
            double deltaHy = equinoctial.getHy() - updated.getHy();
            double deltaLv = MathUtils.normalizeAngle(equinoctial.getLv() - updated.getLv(), 0.0);

            boolean finite = Double.isFinite(deltaA) && Double.isFinite(deltaEx) && Double.isFinite(deltaEy)
                    && Double.isFinite(deltaHx) && Double.isFinite(deltaHy) && Double.isFinite(deltaLv)
                    && Double.isFinite(sma) && Double.isFinite(ex) && Double.isFinite(ey)
                    && Double.isFinite(hx) && Double.isFinite(hy) && Double.isFinite(lv);
            boolean checkpoint = iteration <= 5 || iteration == 10 || iteration == 20 || iteration == 50
                    || iteration == 100 || iteration == 150 || iteration >= 195 || !finite;
            if (checkpoint) {
                log(finite ? "ITER" : "NONFINITE", satelliteId, timeS, iteration, sma, ex, ey, hx, hy, lv,
                        deltaA, deltaEx, deltaEy, deltaHx, deltaHy, deltaLv,
                        thresholdA, thresholdE, thresholdH, thresholdLv);
            }
            if (!finite) {
                break;
            }

            sma += DAMPING * deltaA;
            ex += DAMPING * deltaEx;
            ey += DAMPING * deltaEy;
            hx += DAMPING * deltaHx;
            hy += DAMPING * deltaHy;
            lv += DAMPING * deltaLv;
            mean = new EquinoctialOrbit(sma, ex, ey, hx, hy, lv,
                    PositionAngleType.TRUE, equinoctial.getFrame(), equinoctial.getDate(), equinoctial.getMu());
        }

        logSensitivity(satelliteId, timeS, osculating, attitudeProvider, forceModels, mass);
    }

    private static void logSensitivity(
            String satelliteId,
            double timeS,
            Orbit osculating,
            AttitudeProvider attitudeProvider,
            Collection<DSSTForceModel> forceModels,
            double mass) {
        SpacecraftState osculatingState = new SpacecraftState(osculating).withMass(mass);
        TimeStampedPVCoordinates inputPv = osculatingState.getPVCoordinates();
        for (double damping : DIAGNOSTIC_DAMPINGS) {
            FixedPointConverter converter = new FixedPointConverter(THRESHOLD, MAX_ITERATIONS, damping);
            try {
                SpacecraftState mean = DSSTPropagator.computeMeanState(
                        osculatingState, attitudeProvider, forceModels, converter);
                SpacecraftState roundTrip = DSSTPropagator.computeOsculatingState(mean, attitudeProvider, forceModels);
                TimeStampedPVCoordinates roundTripPv = roundTrip.getPVCoordinates();
                Vector3D deltaR = inputPv.getPosition().subtract(roundTripPv.getPosition());
                Vector3D deltaV = inputPv.getVelocity().subtract(roundTripPv.getVelocity());
                System.err.printf(Locale.ROOT,
                        "DSST_CONVERTER_SENSITIVITY satellite_id=%s time_s=%.1f damping=%.3f threshold=%.3g max_iterations=%d "
                                + "status=SUCCESS iterations=%d roundtrip_dr_m=%.17g roundtrip_dv_m_s=%.17g%n",
                        satelliteId, timeS, damping, THRESHOLD, MAX_ITERATIONS,
                        converter.getIterationsNb(), deltaR.getNorm(), deltaV.getNorm());
            } catch (RuntimeException exception) {
                System.err.printf(Locale.ROOT,
                        "DSST_CONVERTER_SENSITIVITY satellite_id=%s time_s=%.1f damping=%.3f threshold=%.3g max_iterations=%d "
                                + "status=FAILURE iterations=%d exception=%s message=%s%n",
                        satelliteId, timeS, damping, THRESHOLD, MAX_ITERATIONS,
                        converter.getIterationsNb(), exception.getClass().getSimpleName(), sanitize(exception.getMessage()));
            }
        }
    }

    private static String sanitize(String text) {
        return text == null ? "" : text.replace('\n', ' ').replace('\r', ' ');
    }

    private static void log(
            String phase,
            String satelliteId,
            double timeS,
            int iteration,
            double a,
            double ex,
            double ey,
            double hx,
            double hy,
            double lv,
            double deltaA,
            double deltaEx,
            double deltaEy,
            double deltaHx,
            double deltaHy,
            double deltaLv,
            double thresholdA,
            double thresholdE,
            double thresholdH,
            double thresholdLv) {
        double maxRatio = maxFinite(
                ratio(deltaA, thresholdA),
                ratio(deltaEx, thresholdE),
                ratio(deltaEy, thresholdE),
                ratio(deltaHx, thresholdH),
                ratio(deltaHy, thresholdH),
                ratio(deltaLv, thresholdLv));
        System.err.printf(Locale.ROOT,
                "DSST_FIXED_POINT_DIAG phase=%s satellite_id=%s time_s=%.1f iteration=%d "
                        + "a=%.17g ex=%.17g ey=%.17g hx=%.17g hy=%.17g lv=%.17g "
                        + "delta_a=%.17g delta_ex=%.17g delta_ey=%.17g delta_hx=%.17g delta_hy=%.17g delta_lv=%.17g "
                        + "ratio_a=%.17g ratio_ex=%.17g ratio_ey=%.17g ratio_hx=%.17g ratio_hy=%.17g ratio_lv=%.17g max_ratio=%.17g%n",
                phase, satelliteId, timeS, iteration,
                a, ex, ey, hx, hy, lv,
                deltaA, deltaEx, deltaEy, deltaHx, deltaHy, deltaLv,
                ratio(deltaA, thresholdA), ratio(deltaEx, thresholdE), ratio(deltaEy, thresholdE),
                ratio(deltaHx, thresholdH), ratio(deltaHy, thresholdH), ratio(deltaLv, thresholdLv), maxRatio);
    }

    private static double ratio(double residual, double threshold) {
        return Double.isFinite(residual) ? FastMath.abs(residual) / threshold : residual;
    }

    private static double maxFinite(double... values) {
        double max = Double.NEGATIVE_INFINITY;
        for (double value : values) {
            if (Double.isFinite(value)) {
                max = FastMath.max(max, value);
            }
        }
        return max;
    }
}
