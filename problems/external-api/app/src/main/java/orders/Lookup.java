package orders;

import java.util.ArrayList;
import java.util.List;

/** Answers a product's price and stock. Impls wrap the HTTP call with their fault handling; see Impls. */
public interface Lookup {

    Product find(Call call);

    record Product(long price, boolean available) {}

    /** One lookup call. Whoever gives up on it (a deadline) cancels it; the HTTP request registered here is aborted. */
    final class Call {
        final String productId;
        final String requestId;
        final String cohort;
        private final List<Runnable> onCancel = new ArrayList<>();
        private boolean cancelled;

        Call(String productId, String requestId, String cohort) {
            this.productId = productId;
            this.requestId = requestId;
            this.cohort = cohort;
        }

        synchronized void onCancel(Runnable action) {
            if (cancelled) action.run();
            else onCancel.add(action);
        }

        synchronized void cancel() {
            if (cancelled) return;
            cancelled = true;
            onCancel.forEach(Runnable::run);
        }

        synchronized boolean cancelled() {
            return cancelled;
        }
    }
}
