import time
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")

def track_progress(
    items: Iterable[T],
    label: str = "items",
    report_every: int = 100,
) -> Iterator[T]:
    start = time.time()
    count = 0

    for item in items:
        count += 1
        if count % report_every == 0:
            elapsed = time.time() - start
            rate = count / elapsed if elapsed > 0 else 0.0
            print(f"Processed {count} {label} in {elapsed:.1f}s ({rate:.2f} {label}/s)")
        yield item

    elapsed = time.time() - start
    rate = count / elapsed if elapsed > 0 else 0.0
    print(f"Finished {count} {label} in {elapsed:.1f}s ({rate:.2f} {label}/s)")
