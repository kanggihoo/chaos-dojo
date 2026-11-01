package lab.chaos.orders;

import java.io.IOException;
import java.io.InterruptedIOException;
import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.SocketException;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.apache.hc.client5.http.ConnectTimeoutException;
import org.apache.hc.client5.http.classic.methods.HttpUriRequestBase;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.core5.http.ConnectionRequestTimeoutException;
import org.apache.hc.core5.util.Timeout;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpMethod;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Product lookup. The only difference between impls is the wait policy (IMPL + its limits). */
@Component
public class Lookup {

    public record Product(long price, boolean available) {}

    /** Outcome that maps to one row of the status precedence table. */
    public static final class Failure extends RuntimeException {
        final int status;
        final String type;

        Failure(int status, String type, String detail) {
            super(detail);
            this.status = status;
            this.type = type;
        }
    }

    private final RestClient client;
    private final JsonMapper json;
    private final boolean deadlineMode;
    private final long deadlineMs;

    public Lookup(RestClient.Builder builder, JsonMapper json, LookupSettings s) {
        this.json = json;
        this.deadlineMode = s.impl().equals("timeout");
        this.deadlineMs = s.deadlineMs();
        var pool = PoolingHttpClientConnectionManagerBuilder.create()
                .setMaxConnTotal(s.poolMax())
                .setMaxConnPerRoute(s.poolMax())
                .setDefaultConnectionConfig(ConnectionConfig.custom()
                        .setConnectTimeout(Timeout.ofMilliseconds(s.connectTimeoutMs()))
                        .build())
                .build();
        var http = HttpClients.custom()
                .setConnectionManager(pool)
                .disableRedirectHandling()
                .disableAutomaticRetries()
                .setDefaultRequestConfig(RequestConfig.custom()
                        .setConnectionRequestTimeout(Timeout.ofMilliseconds(s.acquireTimeoutMs()))
                        .setResponseTimeout(Timeout.ofMilliseconds(s.responseTimeoutMs()))
                        .build())
                .build();
        var factory = deadlineMode ? new DeadlineFactory(http, deadlineMs) : new HttpComponentsClientHttpRequestFactory(http);
        this.client = builder.baseUrl(s.baseUrl()).requestFactory(factory).build();
    }

    public Product find(String productId, String requestId, String cohort) {
        long start = System.nanoTime();
        try {
            return client.get()
                    .uri("/products/{id}", productId)
                    .header("X-Request-Id", requestId)
                    .header("X-Chaos-Cohort", cohort)
                    .exchange((req, res) -> {
                        int code = res.getStatusCode().value();
                        if (code == 404) throw new Failure(400, "invalid-request", "unknown product " + productId);
                        if (code != 200) throw new Failure(502, "upstream-error", "lookup answered " + code);
                        return parse(res.getBody().readAllBytes(), productId);
                    });
        } catch (Failure f) {
            throw f;
        } catch (ResourceAccessException e) {
            throw classify(e.getCause(), start);
        } catch (RuntimeException e) {
            if (deadlineMode && expired(start)) throw new Failure(504, "upstream-timeout", "lookup deadline exceeded");
            throw e;
        }
    }

    private boolean expired(long startNanos) {
        return System.nanoTime() - startNanos >= TimeUnit.MILLISECONDS.toNanos(deadlineMs);
    }

    private Failure classify(Throwable cause, long start) {
        if (deadlineMode && expired(start)) return new Failure(504, "upstream-timeout", "lookup deadline exceeded");
        if (cause instanceof ConnectionRequestTimeoutException) return new Failure(503, "upstream-unavailable", "lookup pool acquire timed out");
        if (cause instanceof ConnectTimeoutException || cause instanceof ConnectException
                || cause instanceof NoRouteToHostException || cause instanceof UnknownHostException)
            return new Failure(503, "upstream-unavailable", "lookup unreachable: " + cause);
        if (cause instanceof SocketTimeoutException) return new Failure(504, "upstream-timeout", "lookup response timed out");
        if (cause instanceof SocketException || cause instanceof InterruptedIOException || cause instanceof IOException)
            return new Failure(503, "upstream-unavailable", "lookup connection failed: " + cause);
        return new Failure(503, "upstream-unavailable", "lookup failed: " + cause);
    }

    private Product parse(byte[] body, String productId) {
        JsonNode n;
        try {
            n = json.readTree(body);
        } catch (RuntimeException e) {
            throw new Failure(502, "invalid-upstream-response", "lookup body is not JSON");
        }
        JsonNode id = n.get("productId"), price = n.get("price"), cur = n.get("currency"), av = n.get("available");
        boolean ok = n.isObject() && id != null && id.isString() && id.asString().equals(productId)
                && price != null && price.isIntegralNumber() && price.canConvertToLong()
                && price.asLong() >= 1 && price.asLong() <= 1_000_000
                && cur != null && cur.isString() && cur.asString().equals("KRW")
                && av != null && av.isBoolean();
        if (!ok) throw new Failure(502, "invalid-upstream-response", "lookup body violates the contract");
        return new Product(price.asLong(), av.asBoolean());
    }

    /** Cancels the whole call (pool acquire + connect + response) once the deadline passes. */
    static final class DeadlineFactory extends HttpComponentsClientHttpRequestFactory {
        private static final ScheduledExecutorService TIMER = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "lookup-deadline");
            t.setDaemon(true);
            return t;
        });
        private final long deadlineMs;

        DeadlineFactory(org.apache.hc.client5.http.classic.HttpClient http, long deadlineMs) {
            super(http);
            this.deadlineMs = deadlineMs;
        }

        @Override
        protected org.apache.hc.client5.http.classic.methods.HttpUriRequest createHttpUriRequest(HttpMethod method, URI uri) {
            var req = (HttpUriRequestBase) super.createHttpUriRequest(method, uri);
            TIMER.schedule(req::cancel, deadlineMs, TimeUnit.MILLISECONDS);
            return req;
        }
    }

    public record LookupSettings(String impl, String baseUrl, int responseTimeoutMs, int deadlineMs,
                                 int connectTimeoutMs, int poolMax, int acquireTimeoutMs) {}

    @org.springframework.context.annotation.Configuration
    static class Config {
        @org.springframework.context.annotation.Bean
        LookupSettings lookupSettings(@Value("${chaos.impl}") String impl,
                                      @Value("${chaos.lookup.base-url}") String baseUrl,
                                      @Value("${chaos.lookup.response-timeout-ms}") int responseTimeoutMs,
                                      @Value("${chaos.lookup.deadline-ms:0}") int deadlineMs,
                                      @Value("${chaos.lookup.connect-timeout-ms}") int connectTimeoutMs,
                                      @Value("${chaos.lookup.pool-max}") int poolMax,
                                      @Value("${chaos.lookup.acquire-timeout-ms}") int acquireTimeoutMs) {
            if (!impl.equals("naive") && !impl.equals("timeout")) throw new IllegalArgumentException("IMPL must be naive or timeout");
            if (impl.equals("timeout") && deadlineMs <= 0) throw new IllegalArgumentException("timeout impl needs LOOKUP_DEADLINE_MS");
            return new LookupSettings(impl, baseUrl, responseTimeoutMs, deadlineMs, connectTimeoutMs, poolMax, acquireTimeoutMs);
        }
    }
}
