import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders headings, lists and inline code", () => {
    render(<Markdown text={"## Summary\n- one\n- two\n\nUse `pytest` before shipping."} />);
    expect(screen.getByRole("heading", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("pytest")).toBeInTheDocument();
  });

  it("renders fenced code blocks verbatim", () => {
    const { container } = render(<Markdown text={"```python\nprint('hi')\n```"} />);
    expect(container.querySelector("pre code")?.textContent).toBe("print('hi')");
  });

  it("only links http(s) URLs", () => {
    const { container } = render(
      <Markdown text={"[safe](https://example.com) [bad](javascript:alert(1))"} />,
    );
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute("href")).toBe("https://example.com");
    expect(links[0]?.getAttribute("rel")).toContain("noopener");
  });

  it("does not interpret raw HTML", () => {
    const { container } = render(<Markdown text={"<img src=x onerror=alert(1)>"} />);
    expect(container.querySelector("img")).toBeNull();
  });
});
