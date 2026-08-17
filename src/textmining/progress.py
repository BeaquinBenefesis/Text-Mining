import time
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")

def track_progress(
    items: Iterable[T],
    label: str = "items",
    report_every: int = 1000,
) -> Iterator[T]:
    start = time.time()
    relative_start = time.time()
    count = 0
    relative_count = 0
    
    for item in items:
        count += 1
        relative_count += 1
        if count % report_every == 0:
            elapsed = time.time() - start
            relative_elsapsed = time.time() - relative_start
            rate = count / elapsed if elapsed > 0 else 0.0
            relative_rate = relative_count / relative_elsapsed if relative_elsapsed else 0.0
            print(f"Processed {count} {label} in {elapsed:.1f}s ({rate:.2f} {label}/s global speed) ({relative_rate:.2f} {label}/s batch speed)")
            relative_count = 0
            relative_start = time.time()
        yield item

    elapsed = time.time() - start
    rate = count / elapsed if elapsed > 0 else 0.0
    print(f"Finished {count} {label} in {elapsed:.1f}s ({rate:.2f} {label}/s)")
