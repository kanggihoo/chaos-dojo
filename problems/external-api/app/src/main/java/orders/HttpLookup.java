package orders;

import java.io.IOException;
import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.UnknownHostException;

import org.apache.hc.client5.http.ConnectTimeoutException;
import org.apache.hc.client5.http.classic.methods.HttpUriRequest;
import org.apache.hc.client5.http.classic.methods.HttpUriRequestBase;
import org.apache.hc.client5.http.config.ConnectionConfig;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.core5.http.ConnectionRequestTimeoutException;
import org.apache.hc.core5.util.Timeout;
import org.springframework.http.HttpMethod;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static orders.Problem.INVALID_REQUEST;
import static orders.Problem.INVALID_UPSTREAM_RESPONSE;
import static orders.Problem.UPSTREAM_ERROR;
import static orders.Problem.UPSTREAM_TIMEOUT;
import static orders.Problem.UPSTREAM_UNAVAILABLE;

/** GET /products/{id} on the product API, with the client's own limits. No fault handling of its own. */
final class HttpLookup implements Lookup {

    /** The call whose HTTP request is being created on this thread, so cancelling the call aborts that request. */
    private static final ThreadLocal<Call> CURRENT = new ThreadLocal<>();

    private final RestClient client;
    private final JsonMapper json;

    HttpLookup(RestClient.Builder builder, JsonMapper json, String baseUrl,
               int connectTimeoutMs, int poolMax, int acquireTimeoutMs, int responseTimeoutMs) {
        this.json = json;
        var pool = PoolingHttpClientConnectionManagerBuilder.create()
                .setMaxConnTotal(poolMax)
                .setMaxConnPerRoute(poolMax)
                .setDefaultConnectionConfig(ConnectionConfig.custom()
                        .setConnectTimeout(Timeout.ofMilliseconds(connectTimeoutMs))
                        .build())
                .build();
        var http = HttpClients.custom()
                .setConnectionManager(pool)
                .disableRedirectHandling()
                .disableAutomaticRetries()
                .setDefaultRequestConfig(RequestConfig.custom()
                        .setConnectionRequestTimeout(Timeout.ofMilliseconds(acquireTimeoutMs))
                        .setResponseTimeout(Timeout.ofMilliseconds(responseTimeoutMs))
                        .build())
                .build();
        var factory = new HttpComponentsClientHttpRequestFactory(http) {
            @Override
            protected HttpUriRequest createHttpUriRequest(HttpMethod method, URI uri) {
                var req = (HttpUriRequestBase) super.createHttpUriRequest(method, uri);
                CURRENT.get().onCancel(req::cancel);
                return req;
            }
        };
        this.client = builder.baseUrl(baseUrl).requestFactory(factory).build();
    }

    @Override
    public Product find(Call call) {
        CURRENT.set(call);
        try {
            return client.get()
                    .uri("/products/{id}", call.productId)
                    .header("X-Request-Id", call.requestId)
                    .header("X-Chaos-Cohort", call.cohort)
                    .exchange((req, res) -> {
                        int code = res.getStatusCode().value();
                        if (code == 404) throw INVALID_REQUEST.failure("unknown product " + call.productId);
                        if (code != 200) throw UPSTREAM_ERROR.failure("lookup answered " + code);
                        return parse(res.getBody().readAllBytes(), call.productId);
                    });
        } catch (ResourceAccessException e) {
            throw classify(e.getCause());
        } finally {
            CURRENT.remove();
        }
    }

    private static Problem.Failure classify(Throwable cause) {
        return switch (cause) {
            case ConnectionRequestTimeoutException e -> UPSTREAM_UNAVAILABLE.failure("lookup pool acquire timed out");
            case ConnectTimeoutException e -> UPSTREAM_UNAVAILABLE.failure("lookup unreachable: " + e);
            case ConnectException e -> UPSTREAM_UNAVAILABLE.failure("lookup unreachable: " + e);
            case NoRouteToHostException e -> UPSTREAM_UNAVAILABLE.failure("lookup unreachable: " + e);
            case UnknownHostException e -> UPSTREAM_UNAVAILABLE.failure("lookup unreachable: " + e);
            case SocketTimeoutException e -> UPSTREAM_TIMEOUT.failure("lookup response timed out");
            case IOException e -> UPSTREAM_UNAVAILABLE.failure("lookup connection failed: " + e);
            case null, default -> UPSTREAM_UNAVAILABLE.failure("lookup failed: " + cause);
        };
    }

    private Product parse(byte[] body, String productId) {
        JsonNode n;
        try {
            n = json.readTree(body);
        } catch (RuntimeException e) {
            throw INVALID_UPSTREAM_RESPONSE.failure("lookup body is not JSON");
        }
        JsonNode id = n.get("productId"), price = n.get("price"), cur = n.get("currency"), av = n.get("available");
        boolean ok = n.isObject() && id != null && id.isString() && id.asString().equals(productId)
                && price != null && price.isIntegralNumber() && price.canConvertToLong()
                && price.asLong() >= 1 && price.asLong() <= 1_000_000
                && cur != null && cur.isString() && cur.asString().equals("KRW")
                && av != null && av.isBoolean();
        if (!ok) throw INVALID_UPSTREAM_RESPONSE.failure("lookup body violates the contract");
        return new Product(price.asLong(), av.asBoolean());
    }
}
