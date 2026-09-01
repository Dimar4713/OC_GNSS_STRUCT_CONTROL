package ru.aimeton.gnss.orekit;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedDeque;

final class PropagationProgressRegistry {
    private static final int MAX_RETAINED_SNAPSHOTS = 256;

    record Snapshot(
            String telemetryId,
            String state,
            String phase,
            String satelliteId,
            Integer satelliteIndex,
            Integer satelliteTotal,
            Integer pointIndex,
            Integer pointTotal,
            Double timeS,
            String epoch,
            String error,
            long updatedAtUnixMs) {}

    private final ConcurrentHashMap<String, Snapshot> snapshots = new ConcurrentHashMap<>();
    private final ConcurrentLinkedDeque<String> insertionOrder = new ConcurrentLinkedDeque<>();

    Snapshot start(String telemetryId) {
        validateTelemetryId(telemetryId);
        Snapshot snapshot = new Snapshot(
                telemetryId,
                "running",
                "starting",
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                null,
                System.currentTimeMillis());
        snapshots.put(telemetryId, snapshot);
        insertionOrder.remove(telemetryId);
        insertionOrder.addLast(telemetryId);
        prune();
        return snapshot;
    }

    void update(String telemetryId, PropagationEngine.ProgressEvent event) {
        snapshots.computeIfPresent(telemetryId, (ignored, previous) -> new Snapshot(
                telemetryId,
                "running",
                event.phase(),
                event.satelliteId(),
                event.satelliteIndex(),
                event.satelliteTotal(),
                event.pointIndex(),
                event.pointTotal(),
                event.timeS(),
                event.epoch(),
                null,
                System.currentTimeMillis()));
    }

    void complete(String telemetryId) {
        snapshots.computeIfPresent(telemetryId, (ignored, previous) -> new Snapshot(
                telemetryId,
                "completed",
                "completed",
                previous.satelliteId(),
                previous.satelliteIndex(),
                previous.satelliteTotal(),
                previous.pointIndex(),
                previous.pointTotal(),
                previous.timeS(),
                previous.epoch(),
                null,
                System.currentTimeMillis()));
    }

    void fail(String telemetryId, String error) {
        snapshots.computeIfPresent(telemetryId, (ignored, previous) -> new Snapshot(
                telemetryId,
                "failed",
                previous.phase(),
                previous.satelliteId(),
                previous.satelliteIndex(),
                previous.satelliteTotal(),
                previous.pointIndex(),
                previous.pointTotal(),
                previous.timeS(),
                previous.epoch(),
                error,
                System.currentTimeMillis()));
    }

    Snapshot get(String telemetryId) {
        return snapshots.get(telemetryId);
    }

    private void prune() {
        while (snapshots.size() > MAX_RETAINED_SNAPSHOTS) {
            String oldest = insertionOrder.pollFirst();
            if (oldest == null) {
                return;
            }
            snapshots.remove(oldest);
        }
    }

    private static void validateTelemetryId(String telemetryId) {
        if (telemetryId == null || telemetryId.isBlank() || telemetryId.length() > 128) {
            throw new IllegalArgumentException("telemetry id must contain 1..128 characters");
        }
        for (int index = 0; index < telemetryId.length(); index++) {
            char value = telemetryId.charAt(index);
            boolean allowed = Character.isLetterOrDigit(value) || value == '-' || value == '_' || value == '.';
            if (!allowed) {
                throw new IllegalArgumentException("telemetry id contains unsupported characters");
            }
        }
    }
}
