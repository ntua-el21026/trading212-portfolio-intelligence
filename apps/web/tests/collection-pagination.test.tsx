import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CollectionPagination } from "../components/collection-pagination";

describe("collection pagination", () => {
  it("reports page coverage and carries an opaque cursor and filters", () => {
    render(
      <CollectionPagination
        nextCursor="opaque.cursor/value"
        pathname="/holdings"
        preservedQuery={{ search: "world fund", sort: "market_value_desc" }}
        returnedCount={50}
        total={73}
      />,
    );

    expect(screen.getByText(/Showing/)).toHaveTextContent(
      "Showing 50 records on this page out of 73 matching records.",
    );
    expect(screen.getByRole("link", { name: "Next page" })).toHaveAttribute(
      "href",
      "/holdings?search=world+fund&sort=market_value_desc&cursor=opaque.cursor%2Fvalue",
    );
  });

  it("marks the collection end without creating a dead link", () => {
    render(
      <CollectionPagination
        nextCursor={null}
        pathname="/activity"
        returnedCount={7}
        total={7}
      />,
    );

    expect(screen.getByText("End of collection")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Next page" })).toBeNull();
  });
});
