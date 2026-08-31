package ru.aimeton.gnss.orekit;

import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashMap;
import java.util.Map;

import org.orekit.attitudes.FrameAlignedProvider;
import org.orekit.frames.Frame;
import org.orekit.orbits.KeplerianOrbit;
import org.orekit.propagation.analytical.gnss.GLONASSAnalyticalPropagator;
import org.orekit.propagation.analytical.gnss.data.GLONASSAlmanac;
import org.orekit.time.AbsoluteDate;
import org.orekit.utils.TimeStampedPVCoordinates;

final class GlonassAlmanacMeanConversionEngine {
    private final OrekitRuntime runtime;
    private final MeanConversionEngine meanConversionEngine;

    GlonassAlmanacMeanConversionEngine(OrekitRuntime runtime) {
        this.runtime = runtime;
        this.meanConversionEngine = new MeanConversionEngine(runtime);
    }

    MeanConversionResult convert(GlonassAlmanacToMeanRequest request) {
        validateRequest(request);
        LocalDate referenceDate = parseReferenceDate(request.referenceDate());
        Frame outputFrame = runtime.propagationFrame(request.frame());
        GLONASSAlmanac almanac = new GLONASSAlmanac(
                request.frequencyChannel(),
                request.health(),
                referenceDate.getDayOfMonth(),
                referenceDate.getMonthValue(),
                referenceDate.getYear(),
                request.referenceTimeS(),
                request.lambdaRad(),
                request.deltaIRad(),
                request.argumentOfPerigeeRad(),
                request.eccentricity(),
                request.deltaTS(),
                request.deltaTDot(),
                request.gloToUtcS(),
                request.gpsToGloS(),
                request.gloTimeOffsetS(),
                runtime.context().getTimeScales().getGLONASS());
        GLONASSAnalyticalPropagator propagator = almanac.getPropagator(
                runtime.context(),
                FrameAlignedProvider.of(outputFrame),
                outputFrame,
                runtime.bodyFixedFrame(),
                request.spacecraft().initialMassKg());
        AbsoluteDate targetDate = runtime.date(request.targetEpoch(), request.targetTimeScale());
        TimeStampedPVCoordinates pv = propagator.getPVCoordinates(targetDate, outputFrame);
        KeplerianOrbit osculating = new KeplerianOrbit(pv, outputFrame, request.forceModel().muM3S2());

        OsculatingToMeanRequest delegated = new OsculatingToMeanRequest(
                request.targetEpoch(),
                request.frame(),
                request.targetTimeScale(),
                osculating.getA(),
                osculating.getE(),
                osculating.getI(),
                osculating.getPerigeeArgument(),
                osculating.getRightAscensionOfAscendingNode(),
                osculating.getTrueAnomaly(),
                "true",
                request.spacecraft(),
                request.forceModel(),
                request.forceModelFingerprint());
        MeanConversionResult result = meanConversionEngine.convert(delegated);

        Map<String, String> metadata = new LinkedHashMap<>(result.backendMetadata());
        metadata.put("source_authority", "GLONASS-ALMANAC-OREKIT-ANALYTICAL");
        metadata.put("almanac_source_format", "glonass-labelled-authority-v1");
        metadata.put("almanac_source_name", request.sourceName());
        metadata.put("glonass_slot", Integer.toString(request.slot()));
        metadata.put("frequency_channel", Integer.toString(request.frequencyChannel()));
        metadata.put("almanac_epoch", almanac.getDate().toString(runtime.timeScale("GLONASS")));
        metadata.put("glonass_target_epoch", targetDate.toString(runtime.timeScale(request.targetTimeScale())));
        metadata.put("glonass_target_time_scale", request.targetTimeScale());
        metadata.put("input_representation", "glonass-almanac-via-orekit-analytical-osculating-pv");
        metadata.put("conversion_chain", "explicit-GLONASS-almanac->Orekit-GLONASSAlmanac->Orekit-GLONASSAnalyticalPropagator@target-epoch->osculating-PV->inertial-frame->Orekit-DSST-mean");
        return new MeanConversionResult(result.meanOrbit(), metadata);
    }

    private static LocalDate parseReferenceDate(String value) {
        try {
            return LocalDate.parse(value);
        } catch (DateTimeParseException exception) {
            throw new IllegalArgumentException("reference_date must be ISO YYYY-MM-DD", exception);
        }
    }

    private static void validateRequest(GlonassAlmanacToMeanRequest request) {
        if (request.sourceName() == null || request.sourceName().isBlank()) {
            throw new IllegalArgumentException("source_name is mandatory");
        }
        if (request.slot() < 1 || request.slot() > 63) {
            throw new IllegalArgumentException("GLONASS slot must be in 1..63");
        }
        if (request.frequencyChannel() < -7 || request.frequencyChannel() > 6) {
            throw new IllegalArgumentException("GLONASS frequency channel must be in -7..6");
        }
        if (request.referenceDate() == null || request.referenceDate().isBlank()) {
            throw new IllegalArgumentException("reference_date is mandatory");
        }
        if (request.referenceTimeS() < 0.0 || request.referenceTimeS() >= 86400.0) {
            throw new IllegalArgumentException("reference_time_s must be in [0, 86400)");
        }
        if (request.eccentricity() < 0.0 || request.eccentricity() >= 1.0) {
            throw new IllegalArgumentException("eccentricity must be in [0, 1)");
        }
        if (request.frame() == null || request.frame().isBlank()) {
            throw new IllegalArgumentException("frame is mandatory");
        }
        if (request.targetEpoch() == null || request.targetEpoch().isBlank()) {
            throw new IllegalArgumentException("target_epoch is mandatory");
        }
        if (request.targetTimeScale() == null || request.targetTimeScale().isBlank()) {
            throw new IllegalArgumentException("target_time_scale is mandatory");
        }
        if (request.spacecraft() == null) {
            throw new IllegalArgumentException("spacecraft is mandatory");
        }
        if (request.forceModel() == null) {
            throw new IllegalArgumentException("force_model is mandatory");
        }
        if (request.forceModelFingerprint() == null || request.forceModelFingerprint().isBlank()) {
            throw new IllegalArgumentException("force_model_fingerprint is mandatory");
        }
    }
}
