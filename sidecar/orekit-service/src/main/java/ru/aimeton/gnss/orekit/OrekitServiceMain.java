package ru.aimeton.gnss.orekit;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

public final class OrekitServiceMain {
    private static final int MAX_REQUEST_BYTES = 16 * 1024 * 1024;

    private OrekitServiceMain() {}

    public static void main(String[] args) throws Exception {
        String dataPath = requireEnv("OREKIT_DATA_PATH");
        int port = Integer.parseInt(System.getenv().getOrDefault("OREKIT_PORT", "8081"));
        OrekitRuntime runtime = new OrekitRuntime(Path.of(dataPath));
        PropagationEngine engine = new PropagationEngine(runtime);
        ObjectMapper mapper = mapper();

        HttpServer server = HttpServer.create(new InetSocketAddress(port), 32);
        server.createContext("/healthz", exchange -> handleHealth(exchange, mapper, runtime));
        server.createContext("/v1/propagate", exchange -> handlePropagate(exchange, mapper, engine));
        server.setExecutor(Executors.newFixedThreadPool(
                Math.max(2, Runtime.getRuntime().availableProcessors())));
        server.start();
        System.out.printf(
                "orekit-service listening on :%d orekit=%s data_sha256=%s%n",
                port, OrekitRuntime.OREKIT_VERSION, runtime.dataSha256());
    }

    static ObjectMapper mapper() {
        return new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    }

    private static void handleHealth(HttpExchange exchange, ObjectMapper mapper, OrekitRuntime runtime)
            throws IOException {
        if (!"GET".equals(exchange.getRequestMethod())) {
            writeJson(exchange, mapper, 405, Map.of("error", "method_not_allowed"));
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "ok");
        body.put("backend", "orekit");
        body.put("orekit_version", OrekitRuntime.OREKIT_VERSION);
        body.put("orekit_data_sha256", runtime.dataSha256());
        writeJson(exchange, mapper, 200, body);
    }

    private static void handlePropagate(HttpExchange exchange, ObjectMapper mapper, PropagationEngine engine)
            throws IOException {
        if (!"POST".equals(exchange.getRequestMethod())) {
            writeJson(exchange, mapper, 405, Map.of("error", "method_not_allowed"));
            return;
        }
        try {
            byte[] body = exchange.getRequestBody().readNBytes(MAX_REQUEST_BYTES + 1);
            if (body.length > MAX_REQUEST_BYTES) {
                writeJson(exchange, mapper, 413, Map.of("error", "request_too_large"));
                return;
            }
            ApiModels.PropagationRequest request = mapper.readValue(body, ApiModels.PropagationRequest.class);
            ApiModels.PropagationResult result = engine.propagate(request);
            writeJson(exchange, mapper, 200, result);
        } catch (IllegalArgumentException | UnsupportedOperationException exception) {
            writeJson(exchange, mapper, 422, Map.of(
                    "error", "invalid_propagation_request",
                    "detail", safeMessage(exception)));
        } catch (Exception exception) {
            exception.printStackTrace(System.err);
            writeJson(exchange, mapper, 500, Map.of(
                    "error", "orekit_propagation_failed",
                    "detail", safeMessage(exception)));
        }
    }

    private static void writeJson(HttpExchange exchange, ObjectMapper mapper, int status, Object body)
            throws IOException {
        byte[] bytes = mapper.writeValueAsBytes(body);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) {
            output.write(bytes);
        } finally {
            exchange.close();
        }
    }

    private static String safeMessage(Exception exception) {
        String message = exception.getMessage();
        return message == null || message.isBlank() ? exception.getClass().getSimpleName() : message;
    }

    private static String requireEnv(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " is required");
        }
        return value;
    }
}
