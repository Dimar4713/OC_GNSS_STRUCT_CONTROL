package ru.aimeton.gnss.orekit;

import static ru.aimeton.gnss.orekit.ApiModels.*;

import java.util.LinkedHashMap;
import java.util.Map;

import org.orekit.errors.OrekitException;
import org.orekit.frames.Frame;
import org.orekit.orbits.KeplerianOrbit;
import org.orekit.propagation.analytical.tle.TLE;
import org.orekit.propagation.analytical.tle.TLEPropagator;
import org.orekit.utils.TimeStampedPVCoordinates;

final class TleMeanConversionEngine {
    private final OrekitRuntime runtime;
    private final MeanConversionEngine meanConversionEngine;

    TleMeanConversionEngine(OrekitRuntime runtime) {
        this.runtime = runtime;
        this.meanConversionEngine = new MeanConversionEngine(runtime);
    }

    MeanConversionResult convert(TleToMeanRequest request) {
        validateRequest(request);
        final TLE tle;
        try {
            if (!TLE.isFormatOK(request.line1(), request.line2())) {
                throw new IllegalArgumentException("TLE lines do not satisfy Orekit/NORAD format checks");
            }
            tle = new TLE(request.line1(), request.line2(), runtime.timeScale("UTC"));
        } catch (OrekitException exception) {
            throw new IllegalArgumentException("invalid TLE format: " + exception.getMessage(), exception);
        }

        var utc = runtime.timeScale("UTC");
        Frame teme = runtime.temeFrame();
        Frame outputFrame = runtime.propagationFrame(request.frame());
        TLEPropagator propagator = TLEPropagator.selectExtrapolator(tle, teme);
        TimeStampedPVCoordinates pv = propagator.getPVCoordinates(tle.getDate(), outputFrame);
        KeplerianOrbit osculating = new KeplerianOrbit(pv, outputFrame, request.forceModel().muM3S2());

        OsculatingToMeanRequest delegated = new OsculatingToMeanRequest(
                tle.getDate().toString(utc),
                request.frame(),
                "UTC",
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
        metadata.put("source_authority", "NORAD-TLE-SGP4");
        metadata.put("sgp4_frame", "TEME");
        metadata.put("sgp4_epoch", tle.getDate().toString(utc));
        metadata.put("norad_satellite_number", Integer.toString(tle.getSatelliteNumber()));
        metadata.put("input_representation", "tle-sgp4-mean-via-osculating-pv");
        metadata.put("conversion_chain", "TLE->Orekit-SGP4/TEME->osculating-PV->inertial-frame->Orekit-DSST-mean");
        return new MeanConversionResult(result.meanOrbit(), metadata);
    }

    private static void validateRequest(TleToMeanRequest request) {
        if (request.line1() == null || request.line1().length() != 69) {
            throw new IllegalArgumentException("line1 must contain exactly 69 characters");
        }
        if (request.line2() == null || request.line2().length() != 69) {
            throw new IllegalArgumentException("line2 must contain exactly 69 characters");
        }
        if (request.frame() == null || request.frame().isBlank()) {
            throw new IllegalArgumentException("frame is mandatory");
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
