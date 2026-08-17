package ru.aimeton.gnss.orekit;

import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.hipparchus.geometry.euclidean.threed.Vector3D;
import org.hipparchus.ode.nonstiff.DormandPrince853Integrator;
import org.orekit.attitudes.AttitudeProvider;
import org.orekit.attitudes.LofOffset;
import org.orekit.bodies.OneAxisEllipsoid;
import org.orekit.forces.ForceModel;
import org.orekit.forces.gravity.HolmesFeatherstoneAttractionModel;
import org.orekit.forces.gravity.ThirdBodyAttraction;
import org.orekit.forces.gravity.potential.NormalizedSphericalHarmonicsProvider;
import org.orekit.forces.gravity.potential.UnnormalizedSphericalHarmonicsProvider;
import org.orekit.forces.maneuvers.ImpulseManeuver;
import org.orekit.forces.radiation.IsotropicRadiationSingleCoefficient;
import org.orekit.forces.radiation.SolarRadiationPressure;
import org.orekit.frames.Frame;
import org.orekit.frames.LOFType;
import org.orekit.orbits.CartesianOrbit;
import org.orekit.orbits.EquinoctialOrbit;
import org.orekit.orbits.Orbit;
import org.orekit.orbits.PositionAngleType;
import org.orekit.propagation.PropagationType;
import org.orekit.propagation.SpacecraftState;
import org.orekit.propagation.events.DateDetector;
import org.orekit.propagation.numerical.NumericalPropagator;
import org.orekit.propagation.semianalytical.dsst.DSSTPropagator;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTForceModel;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTSolarRadiationPressure;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTTesseral;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTThirdBody;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTZonal;
import org.orekit.time.AbsoluteDate;
import org.orekit.utils.PVCoordinates;
import org.orekit.utils.TimeStampedPVCoordinates;

final class PropagationEngine {
    private static final double GRAVITY_MU_RELATIVE_TOLERANCE = 1.0e-8;
    private static final double INITIAL_MANEUVER_TOLERANCE_S = 1.0e-12;
    private static final double STANDARD_GRAVITY_M_S2 = 9.80665;

    private final OrekitRuntime runtime;

    PropagationEngine(OrekitRuntime runtime) {
        this.runtime = runtime;
    }

    PropagationResult propagate(PropagationRequest request) {
        validateRequest(request);
        List<Double> times = outputTimes(request.durationS(), request.outputStepS());
        Map<String, List<MeanOrbit>> mean = new LinkedHashMap<>();
        Map<String, List<OsculatingState>> cartesian = new LinkedHashMap<>();

        NormalizedSphericalHarmonicsProvider gravityIdentity = runtime.context().getGravityFields()
                .getNormalizedProvider(request.forceModel().gravityDegree(), request.forceModel().gravityOrder());
        validateGravityMu(request.forceModel(), gravityIdentity.getMu());

        for (SatelliteSpec satellite : request.satellites()) {
            SatelliteHistory history = switch (request.forceModel().mode()) {
                case "design" -> propagateDesign(request, satellite, times);
                case "validation" -> propagateValidation(request, satellite, times);
                default -> throw new IllegalArgumentException(
                        "Orekit sidecar accepts only design or validation mode, got: " + request.forceModel().mode());
            };
            mean.put(satellite.satelliteId(), history.mean());
            cartesian.put(satellite.satelliteId(), history.cartesian());
        }

        Map<String, String> metadata = new LinkedHashMap<>();
        metadata.put("orekit_version", OrekitRuntime.OREKIT_VERSION);
        metadata.put("orekit_data_revision", runtime.dataRevision());
        metadata.put("orekit_data_sha256", runtime.dataSha256());
        metadata.put("frame", request.frame());
        metadata.put("time_scale", request.timeScale());
        metadata.put("gravity_degree", Integer.toString(request.forceModel().gravityDegree()));
        metadata.put("gravity_order", Integer.toString(request.forceModel().gravityOrder()));
        metadata.put("gravity_mu_m3_s2", Double.toString(gravityIdentity.getMu()));
        metadata.put("gravity_reference_radius_m", Double.toString(gravityIdentity.getAe()));
        metadata.put("earth_ellipsoid_equatorial_radius_m", Double.toString(request.forceModel().referenceRadiusM()));
        metadata.put("earth_ellipsoid_flattening", Double.toString(request.forceModel().flattening()));
        metadata.put("mean_definition", "DSST force-model-consistent mean equinoctial elements");
        metadata.put("propagation_type", request.forceModel().mode());
        metadata.put("maneuver_frame", "QSW/RTN");
        metadata.put("initial_impulse_policy", "explicit-state-reset-at-epoch");

        String backend = request.forceModel().mode().equals("design")
                ? "orekit-dsst-design"
                : "orekit-numerical-validation";
        return new PropagationResult(
                backend,
                OrekitRuntime.OREKIT_VERSION,
                request.forceModelFingerprint(),
                metadata,
                times,
                mean,
                cartesian);
    }

    private SatelliteHistory propagateDesign(
            PropagationRequest request, SatelliteSpec satellite, List<Double> times) {
        Frame frame = runtime.propagationFrame(request.frame());
        AbsoluteDate epoch = runtime.date(request.epoch(), request.timeScale());
        AttitudeProvider attitude = new LofOffset(frame, LOFType.QSW);
        List<DSSTForceModel> forces = dsstForces(request.forceModel(), satellite.spacecraft());
        SpacecraftState initialMean = new SpacecraftState(toOrekitOrbit(satellite.meanOrbit(), frame, epoch,
                request.forceModel().muM3S2())).withMass(satellite.spacecraft().initialMassKg());

        if (hasInitialImpulse(request, satellite)) {
            SpacecraftState initialOsculating = DSSTPropagator.computeOsculatingState(initialMean, attitude, forces);
            SpacecraftState maneuveredOsculating = applyInitialImpulses(initialOsculating, request, satellite);
            initialMean = DSSTPropagator.computeMeanState(maneuveredOsculating, attitude, forces)
                    .withMass(maneuveredOsculating.getMass());
        }

        DSSTPropagator propagator = new DSSTPropagator(integrator(request.integrator()), PropagationType.MEAN, attitude);
        propagator.setMu(request.forceModel().muM3S2());
        for (DSSTForceModel force : forces) {
            propagator.addForceModel(force);
        }
        propagator.setInitialState(initialMean, PropagationType.MEAN);
        addFutureImpulses(propagator, request, satellite, frame, epoch);

        List<MeanOrbit> mean = new ArrayList<>(times.size());
        List<OsculatingState> cartesian = new ArrayList<>(times.size());
        for (double time : times) {
            SpacecraftState meanState = propagator.propagate(epoch.shiftedBy(time));
            SpacecraftState osculating = DSSTPropagator.computeOsculatingState(meanState, attitude, forces);
            mean.add(toApiMean(meanState.getOrbit(), request.forceModelFingerprint(), "orekit-dsst-13.1.7-design"));
            cartesian.add(toApiCartesian(time, osculating));
        }
        return new SatelliteHistory(mean, cartesian);
    }

    private SatelliteHistory propagateValidation(
            PropagationRequest request, SatelliteSpec satellite, List<Double> times) {
        Frame frame = runtime.propagationFrame(request.frame());
        AbsoluteDate epoch = runtime.date(request.epoch(), request.timeScale());
        AttitudeProvider attitude = new LofOffset(frame, LOFType.QSW);
        List<DSSTForceModel> meanForces = dsstForces(request.forceModel(), satellite.spacecraft());
        SpacecraftState initialMean = new SpacecraftState(toOrekitOrbit(satellite.meanOrbit(), frame, epoch,
                request.forceModel().muM3S2())).withMass(satellite.spacecraft().initialMassKg());
        SpacecraftState initialOsculating = DSSTPropagator.computeOsculatingState(initialMean, attitude, meanForces);
        initialOsculating = applyInitialImpulses(initialOsculating, request, satellite);

        NumericalPropagator propagator = new NumericalPropagator(integrator(request.integrator()), attitude);
        propagator.setInitialState(initialOsculating);
        for (ForceModel force : numericalForces(request.forceModel(), satellite.spacecraft())) {
            propagator.addForceModel(force);
        }
        addFutureImpulses(propagator, request, satellite, frame, epoch);

        List<MeanOrbit> mean = new ArrayList<>(times.size());
        List<OsculatingState> cartesian = new ArrayList<>(times.size());
        for (double time : times) {
            SpacecraftState osculating = propagator.propagate(epoch.shiftedBy(time));
            SpacecraftState meanState = DSSTPropagator.computeMeanState(osculating, attitude, meanForces);
            mean.add(toApiMean(meanState.getOrbit(), request.forceModelFingerprint(),
                    "orekit-dsst-13.1.7-from-numerical"));
            cartesian.add(toApiCartesian(time, osculating));
        }
        return new SatelliteHistory(mean, cartesian);
    }

    private List<DSSTForceModel> dsstForces(ApiModels.ForceModel config, SpacecraftModel spacecraft) {
        if (config.tides()) {
            throw new UnsupportedOperationException(
                    "tides=true cannot yet produce force-model-consistent DSST mean elements");
        }
        if (config.relativity()) {
            throw new UnsupportedOperationException(
                    "relativity=true cannot yet produce force-model-consistent DSST mean elements");
        }
        UnnormalizedSphericalHarmonicsProvider gravity = runtime.context().getGravityFields()
                .getUnnormalizedProvider(config.gravityDegree(), config.gravityOrder());
        validateGravityMu(config, gravity.getMu());
        Frame bodyFixed = runtime.bodyFixedFrame();
        OneAxisEllipsoid earth = new OneAxisEllipsoid(config.referenceRadiusM(), config.flattening(), bodyFixed);
        List<DSSTForceModel> forces = new ArrayList<>();
        if (config.gravityDegree() >= 2) {
            forces.add(new DSSTZonal(bodyFixed, gravity));
        }
        if (config.gravityOrder() > 0) {
            forces.add(new DSSTTesseral(bodyFixed, config.earthRotationRateRadS(), gravity));
        }
        if (config.moon()) {
            forces.add(new DSSTThirdBody(runtime.context().getCelestialBodies().getMoon(), config.muM3S2()));
        }
        if (config.sun()) {
            forces.add(new DSSTThirdBody(runtime.context().getCelestialBodies().getSun(), config.muM3S2()));
        }
        if (config.srp()) {
            forces.add(new DSSTSolarRadiationPressure(
                    spacecraft.cr(), spacecraft.areaM2(), runtime.context().getCelestialBodies().getSun(), earth,
                    config.muM3S2()));
        }
        return forces;
    }

    private List<ForceModel> numericalForces(ApiModels.ForceModel config, SpacecraftModel spacecraft) {
        if (config.tides() || config.relativity()) {
            throw new UnsupportedOperationException(
                    "numerical force configuration cannot yet be mapped to the same DSST mean-element definition");
        }
        NormalizedSphericalHarmonicsProvider gravity = runtime.context().getGravityFields()
                .getNormalizedProvider(config.gravityDegree(), config.gravityOrder());
        validateGravityMu(config, gravity.getMu());
        Frame bodyFixed = runtime.bodyFixedFrame();
        OneAxisEllipsoid earth = new OneAxisEllipsoid(config.referenceRadiusM(), config.flattening(), bodyFixed);
        List<ForceModel> forces = new ArrayList<>();
        if (config.gravityDegree() >= 2) {
            forces.add(new HolmesFeatherstoneAttractionModel(bodyFixed, gravity));
        }
        if (config.moon()) {
            forces.add(new ThirdBodyAttraction(runtime.context().getCelestialBodies().getMoon()));
        }
        if (config.sun()) {
            forces.add(new ThirdBodyAttraction(runtime.context().getCelestialBodies().getSun()));
        }
        if (config.srp()) {
            forces.add(new SolarRadiationPressure(
                    runtime.context().getCelestialBodies().getSun(),
                    earth,
                    new IsotropicRadiationSingleCoefficient(spacecraft.areaM2(), spacecraft.cr())));
        }
        return forces;
    }

    private static DormandPrince853Integrator integrator(Integrator config) {
        return new DormandPrince853Integrator(
                config.minStepS(), config.maxStepS(), config.absTolerance(), config.relTolerance());
    }

    private static boolean hasInitialImpulse(PropagationRequest request, SatelliteSpec satellite) {
        return request.maneuvers().stream().anyMatch(maneuver ->
                maneuver.satelliteId().equals(satellite.satelliteId())
                        && Math.abs(maneuver.timeS()) <= INITIAL_MANEUVER_TOLERANCE_S);
    }

    private static SpacecraftState applyInitialImpulses(
            SpacecraftState initialOsculating,
            PropagationRequest request,
            SatelliteSpec satellite) {
        SpacecraftState state = initialOsculating;
        for (Maneuver maneuver : request.maneuvers()) {
            if (!maneuver.satelliteId().equals(satellite.satelliteId())
                    || Math.abs(maneuver.timeS()) > INITIAL_MANEUVER_TOLERANCE_S) {
                continue;
            }
            validateManeuverVector(maneuver);
            Vector3D localDeltaV = new Vector3D(
                    maneuver.dvRtnMS().get(0), maneuver.dvRtnMS().get(1), maneuver.dvRtnMS().get(2));
            TimeStampedPVCoordinates pv = state.getPVCoordinates();
            Vector3D inertialDeltaV = LOFType.QSW.rotationFromInertial(pv).revert().applyTo(localDeltaV);
            PVCoordinates maneuveredPv = new PVCoordinates(
                    pv.getPosition(),
                    pv.getVelocity().add(inertialDeltaV));
            Orbit maneuveredOrbit = new CartesianOrbit(
                    maneuveredPv,
                    state.getOrbit().getFrame(),
                    state.getDate(),
                    state.getOrbit().getMu());
            double isp = satellite.spacecraft().ispS();
            if (!(isp > 0.0)) {
                throw new IllegalArgumentException("spacecraft isp_s must be positive");
            }
            double massAfter = state.getMass()
                    * Math.exp(-localDeltaV.getNorm() / (STANDARD_GRAVITY_M_S2 * isp));
            state = new SpacecraftState(maneuveredOrbit).withMass(massAfter);
        }
        return state;
    }

    private void addFutureImpulses(
            org.orekit.propagation.Propagator propagator,
            PropagationRequest request,
            SatelliteSpec satellite,
            Frame frame,
            AbsoluteDate epoch) {
        for (Maneuver maneuver : request.maneuvers()) {
            if (!maneuver.satelliteId().equals(satellite.satelliteId())
                    || maneuver.timeS() <= INITIAL_MANEUVER_TOLERANCE_S) {
                continue;
            }
            validateManeuverVector(maneuver);
            Vector3D deltaV = new Vector3D(
                    maneuver.dvRtnMS().get(0), maneuver.dvRtnMS().get(1), maneuver.dvRtnMS().get(2));
            DateDetector trigger = new DateDetector(epoch.shiftedBy(maneuver.timeS()));
            ImpulseManeuver impulse = new ImpulseManeuver(
                    trigger,
                    new LofOffset(frame, LOFType.QSW),
                    deltaV,
                    satellite.spacecraft().ispS());
            propagator.addEventDetector(impulse);
        }
    }

    private static void validateManeuverVector(Maneuver maneuver) {
        if (maneuver.dvRtnMS() == null || maneuver.dvRtnMS().size() != 3) {
            throw new IllegalArgumentException("dv_rtn_m_s must have exactly three components");
        }
        for (Double component : maneuver.dvRtnMS()) {
            if (component == null || !Double.isFinite(component)) {
                throw new IllegalArgumentException("dv_rtn_m_s components must be finite");
            }
        }
    }

    private static EquinoctialOrbit toOrekitOrbit(
            MeanOrbit orbit, Frame frame, AbsoluteDate epoch, double mu) {
        return new EquinoctialOrbit(
                orbit.aM(), orbit.ex(), orbit.ey(), orbit.ix(), orbit.iy(), orbit.lambdaRad(),
                PositionAngleType.MEAN, frame, epoch, mu);
    }

    private static MeanOrbit toApiMean(Orbit orbit, String fingerprint, String theory) {
        EquinoctialOrbit equinoctial = new EquinoctialOrbit(orbit);
        return new MeanOrbit(
                equinoctial.getA(),
                equinoctial.getEquinoctialEx(),
                equinoctial.getEquinoctialEy(),
                equinoctial.getHx(),
                equinoctial.getHy(),
                equinoctial.getLM(),
                new MeanElementDefinition("equinoctial", theory, fingerprint));
    }

    private static OsculatingState toApiCartesian(double time, SpacecraftState state) {
        TimeStampedPVCoordinates pv = state.getPVCoordinates();
        return new OsculatingState(
                time,
                List.of(pv.getPosition().getX(), pv.getPosition().getY(), pv.getPosition().getZ()),
                List.of(pv.getVelocity().getX(), pv.getVelocity().getY(), pv.getVelocity().getZ()));
    }

    private static List<Double> outputTimes(double duration, double step) {
        List<Double> times = new ArrayList<>();
        double time = 0.0;
        while (time < duration) {
            times.add(time);
            time += step;
        }
        if (times.isEmpty() || Math.abs(times.get(times.size() - 1) - duration) > 1.0e-12) {
            times.add(duration);
        }
        return times;
    }

    private static void validateRequest(PropagationRequest request) {
        if (request.forceModelFingerprint() == null || request.forceModelFingerprint().isBlank()) {
            throw new IllegalArgumentException("force_model_fingerprint is mandatory");
        }
        if (request.satellites() == null || request.satellites().isEmpty()) {
            throw new IllegalArgumentException("at least one satellite is required");
        }
        if (request.maneuvers() == null) {
            throw new IllegalArgumentException("maneuvers must be an array, possibly empty");
        }
        for (Maneuver maneuver : request.maneuvers()) {
            if (!Double.isFinite(maneuver.timeS()) || maneuver.timeS() < 0.0 || maneuver.timeS() > request.durationS()) {
                throw new IllegalArgumentException("maneuver time_s must lie inside propagation duration");
            }
            validateManeuverVector(maneuver);
            boolean targetExists = request.satellites().stream()
                    .anyMatch(satellite -> satellite.satelliteId().equals(maneuver.satelliteId()));
            if (!targetExists) {
                throw new IllegalArgumentException("unknown maneuver satellite_id: " + maneuver.satelliteId());
            }
        }
    }

    private static void validateGravityMu(ApiModels.ForceModel config, double providerMu) {
        double muRelative = Math.abs(providerMu - config.muM3S2()) / config.muM3S2();
        if (muRelative > GRAVITY_MU_RELATIVE_TOLERANCE) {
            throw new IllegalArgumentException(
                    "configured central-body mu disagrees with loaded gravity field: mu_rel=" + muRelative);
        }
    }

    private record SatelliteHistory(List<MeanOrbit> mean, List<OsculatingState> cartesian) {}
}
