package lab.chaos.orders;

import org.apache.coyote.AbstractProtocol;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.actuate.autoconfigure.web.ManagementContextConfiguration;
import org.springframework.boot.actuate.autoconfigure.web.ManagementContextType;
import org.springframework.boot.tomcat.servlet.TomcatServletWebServerFactory;
import org.springframework.boot.web.server.WebServerFactoryCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.core.Ordered;

/** The management port gets its own small fixed executor, so readiness and metrics survive worker exhaustion. */
@ManagementContextConfiguration(ManagementContextType.CHILD)
public class ManagementThreads {
    @Bean
    Customizer managementExecutor(@Value("${chaos.management.threads}") int threads) {
        return new Customizer(threads);
    }

    record Customizer(int threads) implements WebServerFactoryCustomizer<TomcatServletWebServerFactory>, Ordered {
        @Override
        public void customize(TomcatServletWebServerFactory factory) {
            factory.addConnectorCustomizers(c -> {
                var p = (AbstractProtocol<?>) c.getProtocolHandler();
                p.setMaxThreads(threads);
                p.setMinSpareThreads(threads);
            });
        }

        @Override
        public int getOrder() {
            return Ordered.LOWEST_PRECEDENCE;  // after the server.tomcat.* customizer, so this executor size wins
        }
    }
}
