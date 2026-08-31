package ru.aimeton.gnss.orekit;

import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.orekit.attitudes.AttitudeProvider;
import org.orekit.attitudes.LofOffset;
import org.orekit.bodies.OneAxisEllipsoid;
import org.orekit.forces.gravity.potential.UnnormalizedSphericalHarmonicsProvider;
import org.orekit.frames.Frame;
import org.orekit.frames.LOFType;
import org.orekit.orbits.EquinoctialOrbit;
import org.orekit.orbits.KeplerianOrbit;
import org.orekit.orbits.PositionAngleType;
import org.orekit.propagation.SpacecraftState;
import org.orekit.propagation.semianalytical.dsst.DSSTPropagator;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTForceModel;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTSolarRadiationPressure;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTTesseral;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTThirdBody;
import org.orekit.propagation.semianalytical.dsst.forces.DSSTZonal;
import org.orekit.time.AbsoluteDate;

final class MeanConversionEngine {
    private static final double GRAVITY_MU_RELATIVE_TOLERANCE = 1.0e-8;

    private final OrekitRuntime runtime;

    MeanConversionEngine(OrekitRuntime runtime) {
        this.runtime = runtime;
    }

    MeanConversionResult convert(OsculatingToMeanRequest request) {
        validateRequest(request);
        Frame frame = runtime.propagationFrame(request.frame());
        AbsoluteDate epoch = runtime.date(request.epoch(), request.timeScale());
        AttitudeProvider attitude = new LofOffset(frame, LOFType.QSW);
        List<DSSTForceModel> forces = dsstForces(request.forceModel(), request.spacecraft());

        PositionAngleType angleType = switch (request.anomalyType()) {
            case "mean" -> PositionAngleType.MEAN;
            case "eccentric" -> PositionAngleType.ECCENTRIC;
            case "true" -> PositionAngleType.TRUE;
            default -> throw new IllegalArgumentException("unsupported anomaly_type: " + request.anomalyType());
        };

        KeplerianOrbit osculatingOrbit = new KeplerianOrbit(
                request.aM(),
                request.e(),
                request.iRad(),
                request.paRad(),
                request.raanRad(),
                request.anomalyRad(),
                angleType,
                frame,
                epoch,
                request.forceModel().muM3S2());
        SpacecraftState osculating = new SpacecraftState(osculatingOrbit)
                .withMass(request.spacecraft().initialMassKg());
        SpacecraftState mean = DSSTPropagator.computeMeanState(osculating, attitude, forces);
        EquinoctialOrbit equinoctial = new EquinoctialOrbit(mean.getOrbit());

        MeanOrbit result = new MeanOrbit(
                equinoctial.getA(),
                equinoctial.getEquinoctialEx(),
                equinoctial.getEquinoctialEy(),
                equinoctial.getHx(),
                equinoctial.getHy(),
                equinoctial.getLM(),
                new MeanElementDefinition(
                        "equinoctial",
                        "orekit-dsst-13.1.7-from-osculating",
                        request.forceModelFingerprint()));

        Map<String, String> metadata = new LinkedHashMap<>();
        metadata.put("backend", "orekit-dsst-mean-conversion");
        metadata.put("orekit_version", OrekitRuntime.OREKIT_VERSION);
        metadata.put("orekit_data_revision", runtime.dataRevision());
        metadata.put("orekit_data_sha256", runtime.dataSha256());
        metadata.put("gravity_model", runtime.gravityModel());
        metadata.put("frame", request.frame());
        metadata.put("time_scale", request.timeScale());
        metadata.put("input_representation", "keplerian-osculating");
        metadata.put("output_representation", "equinoctial-mean");
        metadata.put("anomaly_type", request.anomalyType());

        return new MeanConversionResult(result, metadata);
    }

    private List<DSSTForceModel> dsstForces(ForceModel config, SpacecraftModel spacecraft) {
        if (config.tides()) {
            throw new UnsupportedOperationException(
                    "tides=true cannot yet produce force-model-consistent DSST mean elements");
        }
        if (config.relativity()) {
            throw new UnsupportedOperationException(
                    "relativity=true cannot yet produce force-model-consistent DSST mean elements");
        }
        if (!OrekitRuntime.GRAVITY_MODEL.equals(config.gravityModel())) {
            throw new IllegalArgumentException(
                    "unsupported gravity_model: requested=" + config.gravityModel()
                            + " runtime=" + OrekitRuntime.GRAVITY_MODEL);
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
                    spacecraft.cr(),
                    spacecraft.areaM2(),
                    runtime.context().getCelestialBodies().getSun(),
                    earth,
                    config.muM3S2()));
        }
        return forces;
    }

    private static void validateRequest(OsculatingToMeanRequest request) {
        if (request.forceModelFingerprint() == null || request.forceModelFingerprint().isBlank()) {
            throw new IllegalArgumentException("force_model_fingerprint is mandatory");
        }
        if (request.forceModel() == null) {
            throw new IllegalArgumentException("force_model is mandatory");
        }
        if (request.spacecraft() == null) {
            throw new IllegalArgumentException("spacecraft is mandatory");
        }
        if (!(request.aM() > 0.0) || !Double.isFinite(request.aM())) {
            throw new IllegalArgumentException("a_m must be finite and positive");
        }
        if (!(request.e() >= 0.0 && request.e() < 1.0) || !Double.isFinite(request.e())) {
            throw new IllegalArgumentException("e must be finite and in [0, 1)");
        }
        if (!Double.isFinite(request.iRad()) || request.iRad() < 0.0 || request.iRad() > Math.PI) {
            throw new IllegalArgumentException("i_rad must be finite and in [0, pi]");
        }
        for (double angle : List.of(request.paRad(), request.raanRad(), request.anomalyRad())) {
            if (!Double.isFinite(angle)) {
                throw new IllegalArgumentException("orbital angles must be finite");
            }
        }
    }

    private static void validateGravityMu(ForceModel config, double providerMu) {
        double muRelative = Math.abs(providerMu - config.muM3S2()) / config.muM3S2();
        if (muRelative > GRAVITY_MU_RELATIVE_TOLERANCE) {
            throw new IllegalArgumentException(
                    "configured central-body mu disagrees with loaded gravity field: configured_mu="
                            + config.muM3S2() + " provider_mu=" + providerMu + " mu_rel=" + muRelative);
        }
    }
}
