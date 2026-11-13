package orders;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

import tools.jackson.databind.json.JsonMapper;

/** IMPL name -> how the lookup is wrapped. The only place that reads IMPL; the wrapping order is the handling order. */
@Configuration
class Impls {

    @Bean
    Lookup lookup(@Value("${chaos.impl}") String impl,
                  @Value("${chaos.lookup.deadline-ms:0}") int deadlineMs,
                  RestClient.Builder builder, JsonMapper json,
                  @Value("${chaos.lookup.base-url}") String baseUrl,
                  @Value("${chaos.lookup.connect-timeout-ms}") int connectTimeoutMs,
                  @Value("${chaos.lookup.pool-max}") int poolMax,
                  @Value("${chaos.lookup.acquire-timeout-ms}") int acquireTimeoutMs,
                  @Value("${chaos.lookup.response-timeout-ms}") int responseTimeoutMs) {
        Lookup http = new HttpLookup(builder, json, baseUrl, connectTimeoutMs, poolMax, acquireTimeoutMs, responseTimeoutMs);
        return switch (impl) {
            case "naive" -> http;
            case "timeout" -> new Deadline(positive(deadlineMs, "LOOKUP_DEADLINE_MS"), http);
            default -> throw new IllegalArgumentException("unknown IMPL: " + impl);
        };
    }

    private static int positive(int value, String env) {
        if (value <= 0) throw new IllegalArgumentException(env + " must be set for this IMPL");
        return value;
    }
}
