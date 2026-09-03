package ru.aimeton.gnss.orekit;

import java.util.Collection;

import org.hipparchus.util.MathUtils;
import org.orekit.attitudes.AttitudeProvider;
import org.orekit.orbits.EquinoctialOrbit;
import org.orekit.orbits.PositionAngleType;
import org.orekit.propagation.SpacecraftState;
import org.orekit.propagation.semianalytical.dsst.DSSTPropagator;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTForceModel;

/**
 * Protects DSST osculating-to-mean conversion from a representational precision floor
 * caused by an unwrapped periodic longitude growing until one double ULP exceeds the
 * converter's fixed longitude convergence threshold.
 *
 * <p>The force model, threshold and iteration policy are not changed. Only the branch
 * of the physically periodic longitude is normalized before calling the same Orekit
 * converter. The returned mean longitude is then restored to the original continuous
 * branch so downstream histories do not acquire artificial 2*pi jumps.</p>
 */
final class PrecisionAwareMeanStateConverter {
    static final double DSST_THRESHOLD = 1.0e-13;
    static final double LONGITUDE_THRESHOLD_RAD = Math.PI * DSST_THRESHOLD;

    private PrecisionAwareMeanStateConverter() {}

    static SpacecraftState computeMeanState(
            SpacecraftState osculating,
            AttitudeProvider attitudeProvider,
            Collection<DSSTForceModel> forceModels) {
        EquinoctialOrbit equinoctial = new EquinoctialOrbit(osculating.getOrbit());
        double longitude = equinoctial.getLv();

        if (Math.ulp(longitude) <= LONGITUDE_THRESHOLD_RAD) {
            return DSSTPropagator.computeMeanState(osculating, attitudeProvider, forceModels);
        }

        double normalizedLongitude = MathUtils.normalizeAngle(longitude, 0.0);
        if (Math.ulp(normalizedLongitude) > LONGITUDE_THRESHOLD_RAD) {
            throw new ArithmeticException(
                    "DSST longitude precision floor remains above convergence threshold after normalization: "
                            + "longitude=" + longitude
                            + " normalized=" + normalizedLongitude
                            + " ulp=" + Math.ulp(normalizedLongitude)
                            + " threshold=" + LONGITUDE_THRESHOLD_RAD);
        }

        double branchOffset = longitude - normalizedLongitude;
        EquinoctialOrbit normalizedOrbit = new EquinoctialOrbit(
                equinoctial.getA(),
                equinoctial.getEquinoctialEx(),
                equinoctial.getEquinoctialEy(),
                equinoctial.getHx(),
                equinoctial.getHy(),
                normalizedLongitude,
                PositionAngleType.TRUE,
                equinoctial.getFrame(),
                equinoctial.getDate(),
                equinoctial.getMu());
        SpacecraftState normalizedState = new SpacecraftState(
                normalizedOrbit,
                osculating.getAttitude(),
                osculating.getMass(),
                osculating.getAdditionalDataValues(),
                osculating.getAdditionalStatesDerivatives());

        SpacecraftState normalizedMean = DSSTPropagator.computeMeanState(
                normalizedState, attitudeProvider, forceModels);
        EquinoctialOrbit meanOrbit = new EquinoctialOrbit(normalizedMean.getOrbit());
        EquinoctialOrbit restoredMeanOrbit = new EquinoctialOrbit(
                meanOrbit.getA(),
                meanOrbit.getEquinoctialEx(),
                meanOrbit.getEquinoctialEy(),
                meanOrbit.getHx(),
                meanOrbit.getHy(),
                meanOrbit.getLv() + branchOffset,
                PositionAngleType.TRUE,
                meanOrbit.getFrame(),
                meanOrbit.getDate(),
                meanOrbit.getMu());

        return new SpacecraftState(
                restoredMeanOrbit,
                normalizedMean.getAttitude(),
                normalizedMean.getMass(),
                normalizedMean.getAdditionalDataValues(),
                normalizedMean.getAdditionalStatesDerivatives());
    }
}
