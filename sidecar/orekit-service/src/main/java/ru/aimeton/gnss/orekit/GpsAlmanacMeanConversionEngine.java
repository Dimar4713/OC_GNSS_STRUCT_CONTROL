package ru.aimeton.gnss.orekit;

import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.orekit.frames.Frame;
import org.orekit.gnss.SEMParser;
import org.orekit.gnss.YUMAParser;
import org.orekit.orbits.KeplerianOrbit;
import org.orekit.propagation.analytical.gnss.GNSSPropagator;
import org.orekit.propagation.analytical.gnss.GNSSPropagatorBuilder;
import org.orekit.propagation.analytical.gnss.data.GPSAlmanac;
import org.orekit.time.AbsoluteDate;
import org.orekit.utils.TimeStampedPVCoordinates;

final class GpsAlmanacMeanConversionEngine {
    private final OrekitRuntime runtime;
    private final MeanConversionEngine meanConversionEngine;

    GpsAlmanacMeanConversionEngine(OrekitRuntime runtime) {
        this.runtime = runtime;
        this.meanConversionEngine = new MeanConversionEngine(runtime);
    }

    MeanConversionResult convert(GpsAlmanacToMeanRequest request) {
        validateRequest(request);
        GPSAlmanac almanac = parseAndSelect(request);
        AbsoluteDate targetDate = runtime.date(request.targetEpoch(), request.targetTimeScale());
        Frame outputFrame = runtime.propagationFrame(request.frame());
        GNSSPropagator propagator = new GNSSPropagatorBuilder(almanac, runtime.context().getFrames())
                .eci(outputFrame)
                .ecef(runtime.bodyFixedFrame())
                .mass(request.spacecraft().initialMassKg())
                .build();
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
        metadata.put("source_authority", "GPS-ALMANAC-OREKIT-GNSS");
        metadata.put("almanac_source_format", request.sourceFormat());
        metadata.put("almanac_source_name", request.sourceName());
        metadata.put("gps_prn", Integer.toString(request.prn()));
        metadata.put("almanac_epoch", almanac.getDate().toString(runtime.timeScale("GPS")));
        metadata.put("gnss_target_epoch", targetDate.toString(runtime.timeScale(request.targetTimeScale())));
        metadata.put("gnss_target_time_scale", request.targetTimeScale());
        metadata.put("input_representation", "gps-almanac-via-orekit-gnss-osculating-pv");
        metadata.put("conversion_chain", "YUMA/SEM->Orekit-GPSAlmanac->Orekit-GNSS-propagator@target-epoch->osculating-PV->inertial-frame->Orekit-DSST-mean");
        return new MeanConversionResult(result.meanOrbit(), metadata);
    }

    private GPSAlmanac parseAndSelect(GpsAlmanacToMeanRequest request) {
        List<GPSAlmanac> almanacs;
        byte[] bytes = request.sourceText().getBytes(StandardCharsets.UTF_8);
        try (var input = new ByteArrayInputStream(bytes)) {
            switch (request.sourceFormat()) {
                case "gps-yuma" -> {
                    YUMAParser parser = new YUMAParser(
                            null,
                            runtime.context().getDataProvidersManager(),
                            runtime.context().getTimeScales());
                    parser.loadData(input, request.sourceName());
                    almanacs = parser.getAlmanacs();
                }
                case "gps-sem" -> {
                    SEMParser parser = new SEMParser(
                            null,
                            runtime.context().getDataProvidersManager(),
                            runtime.context().getTimeScales());
                    parser.loadData(input, request.sourceName());
                    almanacs = parser.getAlmanacs();
                }
                default -> throw new UnsupportedOperationException(
                        "GPS almanac authority supports only gps-yuma and gps-sem");
            }
        } catch (Exception exception) {
            if (exception instanceof IllegalArgumentException || exception instanceof UnsupportedOperationException) {
                throw (RuntimeException) exception;
            }
            throw new IllegalArgumentException("Orekit could not parse GPS almanac source: " + exception.getMessage(), exception);
        }
        return almanacs.stream()
                .filter(item -> item.getPRN() == request.prn())
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "requested GPS PRN is absent from parsed almanac: " + request.prn()));
    }

    private static void validateRequest(GpsAlmanacToMeanRequest request) {
        if (request.sourceFormat() == null || request.sourceFormat().isBlank()) {
            throw new IllegalArgumentException("source_format is mandatory");
        }
        if (request.sourceName() == null || request.sourceName().isBlank()) {
            throw new IllegalArgumentException("source_name is mandatory");
        }
        if (request.sourceText() == null || request.sourceText().isBlank()) {
            throw new IllegalArgumentException("source_text is mandatory");
        }
        if (request.prn() <= 0) {
            throw new IllegalArgumentException("prn must be positive");
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
