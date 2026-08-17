package ru.aimeton.gnss.orekit;

import java.util.List;
import java.util.Map;

final class ApiModels {
    private ApiModels() {}

    record MeanElementDefinition(String representation, String theory, String forceModelFingerprint) {}

    record MeanOrbit(
            double aM,
            double ex,
            double ey,
            double ix,
            double iy,
            double lambdaRad,
            MeanElementDefinition definition) {}

    record SpacecraftModel(
            double dryMassKg,
            double propellantMassKg,
            double ispS,
            double areaM2,
            double cr) {
        double initialMassKg() {
            return dryMassKg + propellantMassKg;
        }
    }

    record SatelliteSpec(
            String satelliteId,
            String planeId,
            String role,
            String referenceId,
            MeanOrbit meanOrbit,
            SpacecraftModel spacecraft) {}

    record ForceModel(
            String mode,
            double muM3S2,
            double referenceRadiusM,
            double flattening,
            double j2,
            double earthRotationRateRadS,
            int gravityDegree,
            int gravityOrder,
            boolean moon,
            boolean sun,
            boolean srp,
            boolean tides,
            boolean relativity) {}

    record Integrator(
            double minStepS,
            double maxStepS,
            double absTolerance,
            double relTolerance) {}

    record Maneuver(String satelliteId, double timeS, List<Double> dvRtnMS) {}

    record PropagationRequest(
            String scenarioId,
            String epoch,
            String frame,
            String timeScale,
            List<SatelliteSpec> satellites,
            List<Maneuver> maneuvers,
            double durationS,
            double outputStepS,
            ForceModel forceModel,
            Integrator integrator,
            int seed,
            String forceModelFingerprint) {}

    record OsculatingState(double epochS, List<Double> rM, List<Double> vMS) {}

    record PropagationResult(
            String backend,
            String backendVersion,
            String forceModelFingerprint,
            Map<String, String> backendMetadata,
            List<Double> timesS,
            Map<String, List<MeanOrbit>> meanOrbits,
            Map<String, List<OsculatingState>> cartesianStates) {}
}
