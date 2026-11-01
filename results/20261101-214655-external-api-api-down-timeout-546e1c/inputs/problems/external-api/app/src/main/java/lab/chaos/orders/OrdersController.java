package lab.chaos.orders;

import java.net.URI;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@RestController
public class OrdersController {
    private static final Logger log = LoggerFactory.getLogger(OrdersController.class);
    static final Pattern REQUEST_ID = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    static final Pattern PRODUCT_ID = Pattern.compile("p-(00[1-9]|01[0-9]|020)");
    static final Set<String> COHORTS = Set.of("warmup", "measured", "probe");

    private final Lookup lookup;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final JsonMapper json;

    public OrdersController(Lookup lookup, JdbcTemplate jdbc, TransactionTemplate tx, JsonMapper json) {
        this.lookup = lookup;
        this.jdbc = jdbc;
        this.tx = tx;
        this.json = json;
    }

    @PostMapping("/orders")
    public ResponseEntity<?> create(@RequestHeader(value = "X-Request-Id", required = false) String requestId,
                                    @RequestHeader(value = "X-Chaos-Cohort", required = false) String cohort,
                                    @RequestBody(required = false) byte[] body) {
        if (requestId == null || !REQUEST_ID.matcher(requestId).matches())
            return problem(400, "invalid-request", "X-Request-Id must be a lowercase UUIDv4", requestId);
        if (cohort == null || !COHORTS.contains(cohort))
            return problem(400, "invalid-request", "X-Chaos-Cohort must be warmup, measured or probe", requestId);
        String productId;
        int quantity;
        try {
            JsonNode n = json.readTree(body == null ? new byte[0] : body);
            JsonNode p = n.get("productId"), q = n.get("quantity");
            if (p == null || !p.isString() || !PRODUCT_ID.matcher(p.asString()).matches())
                return problem(400, "invalid-request", "productId must be p-001..p-020", requestId);
            if (q == null || !q.isInt() || q.asInt() < 1 || q.asInt() > 10)
                return problem(400, "invalid-request", "quantity must be an integer 1..10", requestId);
            productId = p.asString();
            quantity = q.asInt();
        } catch (RuntimeException e) {
            return problem(400, "invalid-request", "body must be a JSON object", requestId);
        }

        Lookup.Product product;
        try {
            product = lookup.find(productId, requestId, cohort);  // outside any transaction, no DB connection held
        } catch (Lookup.Failure f) {
            return problem(f.status, f.type, f.getMessage(), requestId);
        }
        if (!product.available()) return problem(409, "product-unavailable", productId + " is not available", requestId);

        long total = product.price() * quantity;
        try {
            Long orderId = tx.execute(s -> jdbc.queryForObject(
                    "INSERT INTO orders (request_id, cohort, product_id, quantity, unit_price, total, currency) "
                            + "VALUES (?, ?, ?, ?, ?, ?, 'KRW') RETURNING id",
                    Long.class, UUID.fromString(requestId), cohort, productId, quantity, product.price(), total));
            Map<String, Object> res = new LinkedHashMap<>();
            res.put("orderId", orderId);
            res.put("requestId", requestId);
            res.put("productId", productId);
            res.put("quantity", quantity);
            res.put("unitPrice", product.price());
            res.put("total", total);
            res.put("currency", "KRW");
            return ResponseEntity.status(201).contentType(MediaType.APPLICATION_JSON).body(res);
        } catch (DuplicateKeyException e) {
            return problem(409, "duplicate-request", "an order with this request id already exists", requestId);
        } catch (DataAccessException e) {
            // TransactionTemplate rolls back before rethrowing an exception from the callback; the checker reads this line.
            log.warn("chaos-rollback requestId={}", requestId);
            return problem(500, "db-error", "order could not be stored", requestId);
        } catch (TransactionException e) {
            // Begin/commit failure: whether the row persisted is unknown, so no rollback is claimed.
            return problem(500, "db-error", "order could not be stored", requestId);
        }
    }

    static ResponseEntity<ProblemDetail> problem(int status, String type, String detail, String requestId) {
        ProblemDetail p = ProblemDetail.forStatusAndDetail(HttpStatus.valueOf(status), detail);
        p.setType(URI.create("urn:chaos-lab:problem:" + type));
        p.setTitle(type);
        p.setProperty("requestId", requestId);
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_PROBLEM_JSON).body(p);
    }
}
