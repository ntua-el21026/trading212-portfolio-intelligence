import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignInPanel } from "../components/sign-in-panel";

describe("SignInPanel", () => {
  it("offers only the explicitly enabled demo entry point", () => {
    render(<SignInPanel demoEnabled localApiAuthEnabled={false} />);

    const button = screen.getByRole("button", {
      name: "Enter demo portfolio",
    });
    expect(button).toBeInTheDocument();
    expect(button.closest("form")).toHaveAttribute(
      "action",
      "/api/auth/demo-session",
    );
  });

  it("offers API-issued local sessions without exposing credentials", () => {
    render(<SignInPanel demoEnabled={false} localApiAuthEnabled />);

    expect(
      screen.getByRole("button", { name: "Start local session" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/HttpOnly session/i)).toBeInTheDocument();
  });

  it("fails closed when neither local mode is enabled", () => {
    render(<SignInPanel demoEnabled={false} localApiAuthEnabled={false} />);

    expect(
      screen.getByText("Authentication is not configured"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
