package orders;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Gives the whole lookup (pool acquire + connect + response) deadlineMs; past it the call is cancelled and answers 504. */
final class Deadline implements Lookup {
    private static final ScheduledExecutorService TIMER = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "lookup-deadline");
        t.setDaemon(true);
        return t;
    });

    private final long deadlineMs;
    private final Lookup inner;

    Deadline(long deadlineMs, Lookup inner) {
        this.deadlineMs = deadlineMs;
        this.inner = inner;
    }

    @Override
    public Product find(Call call) {
        var timer = TIMER.schedule(call::cancel, deadlineMs, TimeUnit.MILLISECONDS);
        try {
            return inner.find(call);
        } catch (RuntimeException e) {
            if (call.cancelled() && !answeredByLookup(e)) throw Problem.UPSTREAM_TIMEOUT.failure("lookup deadline exceeded");
            throw e;
        } finally {
            timer.cancel(false);
        }
    }

    /** A 400 or 502 built from lookup's own response stands even if the deadline passed while reading it. */
    private static boolean answeredByLookup(RuntimeException e) {
        return e instanceof Problem.Failure f
                && f.problem != Problem.UPSTREAM_UNAVAILABLE && f.problem != Problem.UPSTREAM_TIMEOUT;
    }
}
