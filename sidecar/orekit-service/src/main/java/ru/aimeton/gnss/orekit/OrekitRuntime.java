package ru.aimeton.gnss.orekit;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;

import org.orekit.data.DataContext;
import org.orekit.data.DirectoryCrawler;
import org.orekit.data.LazyLoadedDataContext;
import org.orekit.forces.gravity.potential.ICGEMFormatReader;
import org.orekit.frames.Frame;
import org.orekit.time.AbsoluteDate;
import org.orekit.time.DateTimeComponents;
import org.orekit.time.TimeScale;
import org.orekit.utils.IERSConventions;

final class OrekitRuntime {
    static final String OREKIT_VERSION = "13.1.7";
    static final String GRAVITY_MODEL = "EIGEN-6S";
    private static final String GRAVITY_MODEL_FILE_PATTERN = "^eigen-6s-truncated$";

    private final LazyLoadedDataContext context;
    private final String dataSha256;
    private final String dataRevision;

    OrekitRuntime(Path dataPath) throws IOException {
        if (!Files.isDirectory(dataPath)) {
            throw new IllegalArgumentException("OREKIT_DATA_PATH must point to a readable directory: " + dataPath);
        }
        this.dataSha256 = fingerprint(dataPath);
        this.dataRevision = readDataRevision();
        this.context = new LazyLoadedDataContext();
        this.context.getDataProvidersManager().clearProviders();
        this.context.getDataProvidersManager().addProvider(new DirectoryCrawler(dataPath.toFile()));

        // Production gravity authority is explicit. Do not allow Orekit's default
        // reader ordering to select another coefficient family from the same data tree.
        var gravityFields = this.context.getGravityFields();
        gravityFields.clearPotentialCoefficientsReaders();
        gravityFields.addPotentialCoefficientsReader(
                new ICGEMFormatReader(GRAVITY_MODEL_FILE_PATTERN, false, this.context.getTimeScales().getTT()));

        DataContext.setDefault(this.context);
        // Fail at startup if critical time/EOP data cannot be resolved.
        this.context.getTimeScales().getUTC();
        this.context.getFrames().getITRF(IERSConventions.IERS_2010, false);
    }

    LazyLoadedDataContext context() {
        return context;
    }

    String dataSha256() {
        return dataSha256;
    }

    String dataRevision() {
        return dataRevision;
    }

    TimeScale timeScale(String name) {
        return switch (name) {
            case "UTC" -> context.getTimeScales().getUTC();
            case "TAI" -> context.getTimeScales().getTAI();
            case "TT" -> context.getTimeScales().getTT();
            case "GPS" -> context.getTimeScales().getGPS();
            default -> throw new IllegalArgumentException("Unsupported time scale: " + name);
        };
    }

    AbsoluteDate date(String text, String scaleName) {
        return new AbsoluteDate(DateTimeComponents.parseDateTime(text), timeScale(scaleName));
    }

    Frame propagationFrame(String name) {
        return switch (name) {
            case "EME2000" -> context.getFrames().getEME2000();
            case "GCRF" -> context.getFrames().getGCRF();
            case "ICRF" -> throw new IllegalArgumentException(
                    "ICRF is barycentric and is not accepted as an Earth-centered propagation frame");
            case "ITRF" -> throw new IllegalArgumentException(
                    "ITRF is non-inertial and is not accepted as an orbit propagation frame");
            default -> throw new IllegalArgumentException("Unsupported propagation frame: " + name);
        };
    }

    Frame bodyFixedFrame() {
        return context.getFrames().getITRF(IERSConventions.IERS_2010, false);
    }

    private static String readDataRevision() {
        String revision = System.getenv().getOrDefault("OREKIT_DATA_REVISION", "unversioned").trim();
        if (!revision.equals("unversioned") && !revision.matches("[0-9a-f]{40}")) {
            throw new IllegalArgumentException(
                    "OREKIT_DATA_REVISION must be a 40-character lowercase git SHA when provided");
        }
        return revision;
    }

    private static String fingerprint(Path root) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            List<Path> files;
            try (var stream = Files.walk(root)) {
                files = stream.filter(Files::isRegularFile)
                        .filter(path -> !root.relativize(path).startsWith(".git"))
                        .sorted(Comparator.comparing(
                                path -> root.relativize(path).toString().replace('\\', '/')))
                        .toList();
            }
            if (files.isEmpty()) {
                throw new IllegalArgumentException("OREKIT_DATA_PATH contains no physical data files: " + root);
            }
            for (Path file : files) {
                String relative = root.relativize(file).toString().replace('\\', '/');
                digest.update(relative.getBytes(StandardCharsets.UTF_8));
                digest.update((byte) 0);
                try (var input = Files.newInputStream(file)) {
                    byte[] buffer = new byte[64 * 1024];
                    int read;
                    while ((read = input.read(buffer)) >= 0) {
                        digest.update(buffer, 0, read);
                    }
                }
                digest.update((byte) 0xff);
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }
}
