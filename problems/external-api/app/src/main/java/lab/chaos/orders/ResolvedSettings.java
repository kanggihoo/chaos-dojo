package lab.chaos.orders;

import java.util.LinkedHashMap;
import java.util.Map;

import org.apache.catalina.util.ServerInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import tools.jackson.databind.json.JsonMapper;

/** Logs the resolved server, client and pool settings once; the harness copies this line into the results. */
@Component
public class ResolvedSettings {
    private static final Logger log = LoggerFactory.getLogger(ResolvedSettings.class);
    static final String[] KEYS = {
            "chaos.impl", "chaos.lookup.response-timeout-ms", "chaos.lookup.deadline-ms", "chaos.lookup.connect-timeout-ms",
            "chaos.lookup.pool-max", "chaos.lookup.acquire-timeout-ms",
            "server.tomcat.threads.max", "server.tomcat.accept-count", "server.tomcat.max-connections",
            "spring.datasource.hikari.maximum-pool-size", "spring.datasource.hikari.connection-timeout",
            "spring.threads.virtual.enabled", "management.server.port", "chaos.management.threads",
            "management.tracing.sampling.probability", "management.otlp.metrics.export.enabled"};

    private final Environment env;
    private final JsonMapper json;
    private final org.springframework.context.ApplicationContext ctx;

    public ResolvedSettings(Environment env, JsonMapper json, org.springframework.context.ApplicationContext ctx) {
        this.env = env;
        this.json = json;
        this.ctx = ctx;
    }

    public Map<String, Object> resolved() {
        Map<String, Object> m = new LinkedHashMap<>();
        for (String k : KEYS) m.put(k, env.getProperty(k));
        m.put("java.version", System.getProperty("java.version"));
        m.put("tomcat.version", ServerInfo.getServerNumber());
        // What the business connector actually runs with, not just what was configured.
        if (ctx instanceof org.springframework.boot.web.server.context.WebServerApplicationContext w
                && w.getWebServer() instanceof org.springframework.boot.tomcat.TomcatWebServer t) {
            var p = (org.apache.coyote.AbstractProtocol<?>) t.getTomcat().getConnector().getProtocolHandler();
            m.put("actual.business.max-threads", p.getMaxThreads());
            m.put("actual.business.accept-count", p.getAcceptCount());
            m.put("actual.business.max-connections", p.getMaxConnections());
        }
        return m;
    }

    @EventListener(ApplicationReadyEvent.class)
    void ready() {
        log.info("chaos-resolved-settings {}", json.writeValueAsString(resolved()));
    }
}
