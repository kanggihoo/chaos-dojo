package lab.chaos.orders;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** chaos_business_inflight{cohort}: business requests in progress; a request ends after its DB transaction. */
@Component
public class InflightFilter extends OncePerRequestFilter {
    private final Map<String, AtomicInteger> inflight = Map.of(
            "warmup", new AtomicInteger(), "measured", new AtomicInteger(), "probe", new AtomicInteger());

    public InflightFilter(MeterRegistry registry) {
        inflight.forEach((cohort, n) -> Gauge.builder("chaos.business.inflight", n, AtomicInteger::get)
                .tag("cohort", cohort).register(registry));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        AtomicInteger n = inflight.get(String.valueOf(req.getHeader("X-Chaos-Cohort")));
        if (n == null) {
            chain.doFilter(req, res);
            return;
        }
        n.incrementAndGet();
        try {
            chain.doFilter(req, res);
        } finally {
            n.decrementAndGet();
        }
    }
}
