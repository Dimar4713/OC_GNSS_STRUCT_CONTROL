package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

final class PropagationProgressRegistryTest {
    @Test
    void failurePreservesLastExactWorkLocation() {
        PropagationProgressRegistry registry = new PropagationProgressRegistry();
        String telemetryId = "validation-GLO-17";
        registry.start(telemetryId);
        registry.update(
                telemetryId,
                new PropagationEngine.ProgressEvent(
                        "osculating_to_mean",
                        "GLO-17",
                        17,
                        30,
                        4561,
                        35041,
                        4_104_000.0,
                        "2027-02-17T12:00:00Z"));
        registry.fail(telemetryId, "unable to compute mean state after 201 iterations");

        PropagationProgressRegistry.Snapshot snapshot = registry.get(telemetryId);
        assertEquals("failed", snapshot.state());
        assertEquals("osculating_to_mean", snapshot.phase());
        assertEquals("GLO-17", snapshot.satelliteId());
        assertEquals(17, snapshot.satelliteIndex());
        assertEquals(30, snapshot.satelliteTotal());
        assertEquals(4561, snapshot.pointIndex());
        assertEquals(35041, snapshot.pointTotal());
        assertEquals(4_104_000.0, snapshot.timeS());
        assertEquals("2027-02-17T12:00:00Z", snapshot.epoch());
        assertEquals("unable to compute mean state after 201 iterations", snapshot.error());
    }

    @Test
    void unknownTelemetryIdReturnsNull() {
        PropagationProgressRegistry registry = new PropagationProgressRegistry();
        assertNull(registry.get("missing"));
    }
}
