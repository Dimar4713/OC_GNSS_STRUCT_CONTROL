package ru.aimeton.gnss.orekit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

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
        assertTrue(snapshot.error().contains("unable to compute mean state after 201 iterations"));
        assertTrue(snapshot.error().contains("phase=osculating_to_mean"));
        assertTrue(snapshot.error().contains("satellite_id=GLO-17"));
        assertTrue(snapshot.error().contains("satellite_index=17/30"));
        assertTrue(snapshot.error().contains("point_index=4561/35041"));
        assertTrue(snapshot.error().contains("time_s=4104000.0"));
        assertTrue(snapshot.error().contains("epoch=2027-02-17T12:00:00Z"));
    }

    @Test
    void unknownTelemetryIdReturnsNull() {
        PropagationProgressRegistry registry = new PropagationProgressRegistry();
        assertNull(registry.get("missing"));
    }
}
