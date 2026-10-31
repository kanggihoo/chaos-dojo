package lab.chaos.orders;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.get;
import static com.github.tomakehurst.wiremock.client.WireMock.okJson;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;
import static org.assertj.core.api.Assertions.assertThat;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

import com.github.tomakehurst.wiremock.WireMockServer;
import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;

/** Status precedence table, no-order-on-error, lookup outside the transaction, readiness, impl settings. */
class OrdersContractTest {
    static WireMockServer wm;
    static ConfigurableApplicationContext naive, timeout;
    static JdbcTemplate db;
    static final HttpClient http = HttpClient.newHttpClient();

    static ConfigurableApplicationContext start(String impl, Map<String, Object> extra) {
        Map<String, Object> p = new java.util.HashMap<>(Map.ofEntries(
                Map.entry("IMPL", impl), Map.entry("LOOKUP_BASE_URL", "http://localhost:" + wm.port()),
                Map.entry("LOOKUP_RESPONSE_TIMEOUT_MS", "800"), Map.entry("LOOKUP_CONNECT_TIMEOUT_MS", "1000"),
                Map.entry("HTTP_POOL_MAX", "50"), Map.entry("HTTP_POOL_ACQUIRE_TIMEOUT_MS", "2000"),
                Map.entry("TOMCAT_MAX_THREADS", "50"), Map.entry("TOMCAT_ACCEPT_COUNT", "100"), Map.entry("TOMCAT_MAX_CONNECTIONS", "200"),
                Map.entry("DB_URL", System.getenv("DB_URL")), Map.entry("DB_USER", "orders"), Map.entry("DB_PASSWORD", "orders"),
                Map.entry("JDBC_POOL_SIZE", "10"), Map.entry("JDBC_CONNECTION_TIMEOUT_MS", "5000"),
                Map.entry("MANAGEMENT_PORT", "0"), Map.entry("MANAGEMENT_THREADS", "4"), Map.entry("TRACE_SAMPLING", "1.0"),
                Map.entry("OTLP_ENDPOINT", "http://localhost:1"), Map.entry("SERVER_PORT", "0")));
        if (impl.equals("timeout")) p.put("LOOKUP_DEADLINE_MS", "300");
        p.putAll(extra);
        return new SpringApplicationBuilder(OrdersApplication.class).properties(p).run();
    }

    @BeforeAll
    static void up() {
        wm = new WireMockServer(options().dynamicPort());
        wm.start();
        naive = start("naive", Map.of());
        timeout = start("timeout", Map.of());
        db = naive.getBean(JdbcTemplate.class);
    }

    @AfterAll
    static void down() {
        naive.close();
        timeout.close();
        wm.stop();
    }

    @BeforeEach
    void reset() {
        wm.resetAll();
        db.update("DELETE FROM orders");
    }

    static int port(ConfigurableApplicationContext ctx) {
        return ((WebServerApplicationContext) ctx).getWebServer().getPort();
    }

    static String product(String id, long price, boolean available) {
        return "{\"productId\":\"" + id + "\",\"price\":" + price + ",\"currency\":\"KRW\",\"available\":" + available + "}";
    }

    static void stub(String id, Consumer<com.github.tomakehurst.wiremock.client.ResponseDefinitionBuilder> r) {
        var b = aResponse();
        r.accept(b);
        wm.stubFor(get(urlEqualTo("/products/" + id)).willReturn(b));
    }

    record Res(int status, String body, String requestId) {}

    static Res order(ConfigurableApplicationContext ctx, String requestId, String cohort, String body) throws Exception {
        var b = HttpRequest.newBuilder(URI.create("http://localhost:" + port(ctx) + "/orders"))
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body));
        if (requestId != null) b.header("X-Request-Id", requestId);
        if (cohort != null) b.header("X-Chaos-Cohort", cohort);
        var r = http.send(b.build(), HttpResponse.BodyHandlers.ofString());
        return new Res(r.statusCode(), r.body(), requestId);
    }

    static Res order(ConfigurableApplicationContext ctx, String productId) throws Exception {
        return order(ctx, UUID.randomUUID().toString(), "measured", "{\"productId\":\"" + productId + "\",\"quantity\":3}");
    }

    static int stored(String requestId) {
        return db.queryForObject("SELECT count(*) FROM orders WHERE request_id = ?::uuid", Integer.class, requestId);
    }

    static void assertProblem(Res r, int status, String type) {
        assertThat(r.status()).as(r.body()).isEqualTo(status);
        assertThat(r.body()).contains("urn:chaos-lab:problem:" + type);
        if (r.requestId() != null && r.requestId().matches("[0-9a-f-]{36}")) assertThat(stored(r.requestId())).isZero();
    }

    @Test
    void createsOrderAfterLookup() throws Exception {
        wm.stubFor(get(urlEqualTo("/products/p-001")).willReturn(okJson(product("p-001", 1500, true))));
        Res r = order(naive, "p-001");
        assertThat(r.status()).isEqualTo(201);
        assertThat(r.body()).contains("\"unitPrice\":1500", "\"total\":4500", "\"currency\":\"KRW\"");
        assertThat(stored(r.requestId())).isEqualTo(1);
        var row = db.queryForMap("SELECT cohort, product_id, quantity, unit_price, total FROM orders");
        assertThat(row).containsEntry("cohort", "measured").containsEntry("unit_price", 1500L).containsEntry("total", 4500L);
        wm.verify(com.github.tomakehurst.wiremock.client.WireMock.getRequestedFor(urlEqualTo("/products/p-001"))
                .withHeader("X-Request-Id", com.github.tomakehurst.wiremock.client.WireMock.equalTo(r.requestId()))
                .withHeader("X-Chaos-Cohort", com.github.tomakehurst.wiremock.client.WireMock.equalTo("measured")));
    }

    @Test
    void row1InvalidRequest() throws Exception {
        String id = UUID.randomUUID().toString();
        assertProblem(order(naive, null, "measured", "{\"productId\":\"p-001\",\"quantity\":1}"), 400, "invalid-request");
        assertProblem(order(naive, id.toUpperCase(), "measured", "{\"productId\":\"p-001\",\"quantity\":1}"), 400, "invalid-request");
        assertProblem(order(naive, id, "other", "{\"productId\":\"p-001\",\"quantity\":1}"), 400, "invalid-request");
        assertProblem(order(naive, id, "measured", "{\"productId\":\"p-021\",\"quantity\":1}"), 400, "invalid-request");
        assertProblem(order(naive, id, "measured", "{\"productId\":\"p-001\",\"quantity\":11}"), 400, "invalid-request");
        assertProblem(order(naive, id, "measured", "{\"productId\":\"p-001\",\"quantity\":1.5}"), 400, "invalid-request");
        assertProblem(order(naive, id, "measured", "not json"), 400, "invalid-request");
        assertThat(wm.getAllServeEvents()).isEmpty();
    }

    @Test
    void row2UpstreamTimeout() throws Exception {
        stub("p-002", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-002", 2500, true)).withFixedDelay(1500));
        assertProblem(order(naive, "p-002"), 504, "upstream-timeout");   // response limit (800 ms here)
        long t = System.nanoTime();
        assertProblem(order(timeout, "p-002"), 504, "upstream-timeout"); // 300 ms whole-call deadline
        assertThat((System.nanoTime() - t) / 1_000_000).isLessThan(800);
    }

    @Test
    void row2DeadlineCoversPoolAcquire() throws Exception {
        var ctx = start("timeout", Map.of("HTTP_POOL_MAX", "1", "LOOKUP_DEADLINE_MS", "300", "LOOKUP_RESPONSE_TIMEOUT_MS", "5000"));
        try {
            stub("p-003", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-003", 3500, true)).withFixedDelay(1000));
            var first = CompletableFuture.supplyAsync(() -> { try { return order(ctx, "p-003"); } catch (Exception e) { throw new RuntimeException(e); } });
            Thread.sleep(100);
            assertProblem(order(ctx, "p-003"), 504, "upstream-timeout");
            assertProblem(first.get(), 504, "upstream-timeout");
        } finally {
            ctx.close();
        }
    }

    @Test
    void row3UpstreamUnavailable() throws Exception {
        var refused = start("naive", Map.of("LOOKUP_BASE_URL", "http://localhost:1"));
        try {
            assertProblem(order(refused, "p-001"), 503, "upstream-unavailable");
        } finally {
            refused.close();
        }
        stub("p-004", b -> b.withFault(com.github.tomakehurst.wiremock.http.Fault.CONNECTION_RESET_BY_PEER));
        assertProblem(order(naive, "p-004"), 503, "upstream-unavailable");
        var tiny = start("naive", Map.of("HTTP_POOL_MAX", "1", "HTTP_POOL_ACQUIRE_TIMEOUT_MS", "200", "LOOKUP_RESPONSE_TIMEOUT_MS", "5000"));
        try {
            stub("p-005", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-005", 5500, true)).withFixedDelay(1000));
            var first = CompletableFuture.supplyAsync(() -> { try { return order(tiny, "p-005"); } catch (Exception e) { throw new RuntimeException(e); } });
            Thread.sleep(100);
            assertProblem(order(tiny, "p-005"), 503, "upstream-unavailable");  // pool acquire timeout
            assertThat(first.get().status()).isEqualTo(201);
        } finally {
            tiny.close();
        }
    }

    @Test
    void row4UnknownProduct() throws Exception {
        stub("p-006", b -> b.withStatus(404));
        assertProblem(order(naive, "p-006"), 400, "invalid-request");
    }

    @Test
    void row5UpstreamError() throws Exception {
        for (int status : List.of(500, 503, 302, 204, 400)) {
            wm.resetAll();
            stub("p-007", b -> b.withStatus(status).withHeader("Location", "http://localhost:" + wm.port() + "/products/p-008"));
            assertProblem(order(naive, "p-007"), 502, "upstream-error");
        }
    }

    @Test
    void row6InvalidUpstreamResponse() throws Exception {
        for (String body : List.of("not json", "{\"productId\":\"p-009\",\"price\":1}", product("p-010", 100, true),
                product("p-009", 0, true), product("p-009", 1_000_001, true),
                "{\"productId\":\"p-009\",\"price\":\"100\",\"currency\":\"KRW\",\"available\":true}",
                "{\"productId\":\"p-009\",\"price\":100,\"currency\":\"USD\",\"available\":false}")) {  // broken body wins over available=false
            wm.resetAll();
            stub("p-009", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(body));
            assertProblem(order(naive, "p-009"), 502, "invalid-upstream-response");
        }
    }

    @Test
    void row7ProductUnavailable() throws Exception {
        stub("p-011", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-011", 11500, false)));
        assertProblem(order(naive, "p-011"), 409, "product-unavailable");
    }

    @Test
    void row8DuplicateRequest() throws Exception {
        stub("p-012", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-012", 12500, true)));
        String id = UUID.randomUUID().toString();
        String body = "{\"productId\":\"p-012\",\"quantity\":1}";
        assertThat(order(naive, id, "measured", body).status()).isEqualTo(201);
        Res again = order(naive, id, "measured", body);
        assertThat(again.status()).isEqualTo(409);
        assertThat(again.body()).contains("urn:chaos-lab:problem:duplicate-request");
        assertThat(stored(id)).isEqualTo(1);
    }

    @Test
    void row9DbError() throws Exception {
        stub("p-013", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-013", 13500, true)));
        db.execute("ALTER TABLE orders ADD CONSTRAINT test_reject CHECK (total < 0) NOT VALID");
        try {
            assertProblem(order(naive, "p-013"), 500, "db-error");
        } finally {
            db.execute("ALTER TABLE orders DROP CONSTRAINT test_reject");
        }
    }

    @Test
    void frameworkErrorsAreProblems() throws Exception {
        var get = http.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port(naive) + "/orders")).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(get.statusCode()).isEqualTo(405);
        assertThat(get.headers().firstValue("Content-Type").orElse("")).contains("application/problem+json");
        var missing = http.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port(naive) + "/nope")).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(missing.statusCode()).isEqualTo(404);
        assertThat(missing.headers().firstValue("Content-Type").orElse("")).contains("application/problem+json");
    }

    @Test
    void lookupHoldsNoDbConnection() throws Exception {
        stub("p-014", b -> b.withStatus(200).withHeader("Content-Type", "application/json").withBody(product("p-014", 14500, true)).withFixedDelay(600));
        var pool = naive.getBean(HikariDataSource.class).getHikariPoolMXBean();
        var call = CompletableFuture.supplyAsync(() -> { try { return order(naive, "p-014"); } catch (Exception e) { throw new RuntimeException(e); } });
        int maxActive = 0;
        for (int i = 0; i < 20 && !call.isDone(); i++) {
            if (wm.getAllServeEvents().size() == 1) maxActive = Math.max(maxActive, pool.getActiveConnections());
            Thread.sleep(20);
        }
        assertThat(call.get().status()).isEqualTo(201);
        assertThat(maxActive).isZero();
    }

    @Test
    void readinessIgnoresLookup() throws Exception {
        int mgmt;
        try (var socket = new java.net.ServerSocket(0)) {
            mgmt = socket.getLocalPort();
        }
        var refused = start("naive", Map.of("LOOKUP_BASE_URL", "http://localhost:1", "MANAGEMENT_PORT", String.valueOf(mgmt)));
        try {
            var r = http.send(HttpRequest.newBuilder(URI.create("http://localhost:" + mgmt + "/actuator/health/readiness")).GET().build(),
                    HttpResponse.BodyHandlers.ofString());
            assertThat(r.statusCode()).isEqualTo(200);
            assertThat(r.body()).contains("UP");
        } finally {
            refused.close();
        }
    }

    @Test
    void implsDifferOnlyInWaitPolicy() {
        Map<String, Object> a = new java.util.HashMap<>(naive.getBean(ResolvedSettings.class).resolved());
        Map<String, Object> b = new java.util.HashMap<>(timeout.getBean(ResolvedSettings.class).resolved());
        assertThat(a.get("spring.threads.virtual.enabled")).isEqualTo("false");
        assertThat(a).containsEntry("actual.business.max-threads", 50).containsEntry("actual.business.accept-count", 100)
                .containsEntry("actual.business.max-connections", 200);
        for (String k : List.of("chaos.impl", "chaos.lookup.deadline-ms", "chaos.lookup.response-timeout-ms")) { a.remove(k); b.remove(k); }
        assertThat(a).isEqualTo(b);
    }
}
