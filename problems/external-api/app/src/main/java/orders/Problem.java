package orders;

/** Every failure the orders API answers with. Types match openapi.yaml; the spec's precedence table picks one. */
enum Problem {
    INVALID_REQUEST(400, "invalid-request"),
    PRODUCT_UNAVAILABLE(409, "product-unavailable"),
    DUPLICATE_REQUEST(409, "duplicate-request"),
    DB_ERROR(500, "db-error"),
    UPSTREAM_ERROR(502, "upstream-error"),
    INVALID_UPSTREAM_RESPONSE(502, "invalid-upstream-response"),
    UPSTREAM_UNAVAILABLE(503, "upstream-unavailable"),
    UPSTREAM_TIMEOUT(504, "upstream-timeout");

    final int status;
    final String type;

    Problem(int status, String type) {
        this.status = status;
        this.type = type;
    }

    Failure failure(String detail) {
        return new Failure(this, detail);
    }

    static final class Failure extends RuntimeException {
        final Problem problem;

        Failure(Problem problem, String detail) {
            super(detail);
            this.problem = problem;
        }
    }
}
