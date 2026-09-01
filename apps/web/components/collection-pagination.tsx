import { ArrowRight } from "lucide-react";
import Link from "next/link";

interface CollectionPaginationProps {
  nextCursor: string | null;
  pathname: string;
  preservedQuery?: Readonly<Record<string, string | undefined>>;
  returnedCount: number;
  total: number;
}

function nextPageHref(
  pathname: string,
  cursor: string,
  preservedQuery: Readonly<Record<string, string | undefined>>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(preservedQuery)) {
    if (value) query.set(key, value);
  }
  query.set("cursor", cursor);
  return `${pathname}?${query.toString()}`;
}

export function CollectionPagination({
  nextCursor,
  pathname,
  preservedQuery = {},
  returnedCount,
  total,
}: Readonly<CollectionPaginationProps>) {
  return (
    <nav className="collection-pagination" aria-label="Collection pagination">
      <p aria-live="polite">
        Showing <strong>{returnedCount}</strong>{" "}
        {returnedCount === 1 ? "record" : "records"} on this page out of{" "}
        <strong>{total}</strong> matching {total === 1 ? "record" : "records"}.
      </p>
      {nextCursor ? (
        <Link
          className="collection-pagination__next"
          href={nextPageHref(pathname, nextCursor, preservedQuery)}
          prefetch={false}
          rel="next"
        >
          Next page <ArrowRight aria-hidden="true" size={16} />
        </Link>
      ) : (
        <span className="collection-pagination__end">End of collection</span>
      )}
    </nav>
  );
}
