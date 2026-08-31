"use client";

import { AlertTriangle } from "lucide-react";

import { Button, EmptyState, Surface } from "@trading212/ui";

export default function PortfolioError({
  reset,
}: Readonly<{ reset: () => void }>) {
  return (
    <Surface>
      <EmptyState
        action={<Button onClick={reset}>Try again</Button>}
        description="The portfolio service could not provide this view. Your data was not changed. Retry, or verify the local API connection."
        icon={<AlertTriangle aria-hidden="true" size={22} />}
        title="Portfolio data unavailable"
      />
    </Surface>
  );
}
