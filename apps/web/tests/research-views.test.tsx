import type { AnchorHTMLAttributes } from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ResearchExposure,
  ResearchItem,
  ResearchNote,
} from "../components/research-views";
import { readResearchQuery } from "../lib/research-query";
import { account, at, id, item, note, other } from "./research-ui-fixtures";
vi.mock("../components/research-forms", () => ({
  ResearchNoteForm: () => null,
  ResearchReviewControl: () => null,
}));
vi.mock("../components/navigation-intent", () => ({
  default: ({ href, children }: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href}>{children}</a>
  ),
}));
describe("source facts and exact copied exposure", () => {
  it("renders source assertions as inert prose without changing the saved exposure", () => {
    const query = readResearchQuery(
      { account, view: "item", item: id },
      new Date(at),
    );
    const { container } = render(
      <ResearchItem item={item} query={query} canWrite={false} detailed />,
    );
    expect(screen.getByLabelText("Source facts")).toHaveTextContent(
      "<script>window.fake = 1</script> Source assertion 999 EUR",
    );
    expect(container.querySelector("script")).toBeNull();
    const facts = screen.getByTestId("research-portfolio-facts");
    expect(facts).toHaveTextContent("560.000000000000000001 EUR");
    expect(facts).not.toHaveTextContent("999 EUR");
    expect(facts).toHaveTextContent("partial · lower_bound");
    expect(facts).toHaveTextContent("2 omitted");
    expect(screen.getByText(/Optional synthesis:/)).toHaveTextContent(
      "unavailable · disabled",
    );
  });
  it("distinguishes unavailable from exact zero and preserves the currency", () => {
    const { rerender } = render(
      <ResearchExposure
        value={{
          ...item.portfolio,
          availability: "unavailable",
          effective_exposure: null,
          reason: "entity_absent_from_capture",
        }}
      />,
    );
    expect(screen.getByText(/Unavailable ·/)).toHaveTextContent(
      "entity_absent_from_capture",
    );
    expect(screen.queryByText("0 EUR")).not.toBeInTheDocument();
    rerender(
      <ResearchExposure
        value={{
          ...item.portfolio,
          effective_exposure: { amount: "0", currency: "EUR" },
        }}
      />,
    );
    expect(screen.getByText("0 EUR")).toBeVisible();
  });
  it("keeps owner prose and immutable identities separate", () => {
    const { container } = render(<ResearchNote value={note} />);
    expect(
      within(screen.getByTestId("research-owner-note")).getByText(
        note.content.thesis!,
      ),
    ).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(note.content_digest)).toBeInTheDocument();
  });
  it("links the exact detailed item to reports and removes the link for a different account", () => {
    const query = readResearchQuery(
      { account, view: "item", item: id },
      new Date(at),
    );
    const view = render(
      <ResearchItem item={item} query={query} canWrite={false} detailed />,
    );
    expect(
      screen.getByRole("link", {
        name: "Create a report from this retained research item",
      }),
    ).toHaveAttribute(
      "href",
      `/reports/premium?profile=report_sections_v3&family=research&account=${account}&item=${id}`,
    );
    view.rerender(
      <ResearchItem
        item={item}
        query={{ ...query, account: other }}
        canWrite={false}
        detailed
      />,
    );
    expect(
      screen.queryByRole("link", {
        name: "Create a report from this retained research item",
      }),
    ).not.toBeInTheDocument();
  });
});
