import { Skeleton, Surface } from "@trading212/ui";

export default function PortfolioLoading() {
  return (
    <div aria-busy="true" aria-label="Loading portfolio" className="page-stack">
      <div className="loading-heading">
        <Skeleton height="2.3rem" width="12rem" />
        <Skeleton height="1rem" width="20rem" />
      </div>
      <Surface className="loading-panel" compact>
        <div className="loading-metrics">
          <Skeleton height="6.5rem" />
          <Skeleton height="6.5rem" />
          <Skeleton height="6.5rem" />
          <Skeleton height="6.5rem" />
        </div>
        <Skeleton height="18rem" />
        <Skeleton height="16rem" />
      </Surface>
      <span className="ui-visually-hidden">Loading portfolio data…</span>
    </div>
  );
}
