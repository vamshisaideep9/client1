import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Capture the props DialogContent hands to the Radix primitive so the outside
// dismissal rule can be exercised without a DOM.
type ContentProps = { onInteractOutside?: (event: Event) => void };

const captured = vi.hoisted(() => ({ props: null as ContentProps | null }));

vi.mock("radix-ui", () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
  return {
    Dialog: {
      Root: passthrough,
      Trigger: passthrough,
      Portal: passthrough,
      Close: passthrough,
      Overlay: () => null,
      Title: passthrough,
      Description: passthrough,
      Content: (props: { children?: React.ReactNode; onInteractOutside?: (event: Event) => void }) => {
        captured.props = props;
        return <div data-testid="content">{props.children}</div>;
      },
    },
  };
});

import { DialogContent } from "@/components/ui/dialog";

function outsideEvent() {
  return new Event("dismissableLayer.pointerDownOutside", { cancelable: true });
}

function render(element: React.ReactElement) {
  captured.props = null;
  renderToStaticMarkup(element);
  // Set by the mocked primitive during render, which TS cannot see.
  const props = captured.props as ContentProps | null;
  if (!props) throw new Error("DialogContent did not render the primitive");
  return props;
}

describe("DialogContent outside dismissal", () => {
  beforeEach(() => {
    captured.props = null;
  });

  it("keeps the default Radix dismissal for read-only dialogs", () => {
    const props = render(<DialogContent>Details</DialogContent>);
    const event = outsideEvent();
    props.onInteractOutside?.(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("stays open on an outside press or focus move when preventOutsideClose is set", () => {
    const props = render(<DialogContent preventOutsideClose>Form</DialogContent>);
    for (const type of ["dismissableLayer.pointerDownOutside", "dismissableLayer.focusOutside"]) {
      const event = new Event(type, { cancelable: true });
      props.onInteractOutside?.(event);
      expect(event.defaultPrevented).toBe(true);
    }
  });

  it("still calls the caller's own onInteractOutside first", () => {
    const seen: boolean[] = [];
    const props = render(
      <DialogContent
        preventOutsideClose
        onInteractOutside={(event) => seen.push(event.defaultPrevented)}
      >
        Form
      </DialogContent>,
    );
    const event = outsideEvent();
    props.onInteractOutside?.(event);
    expect(seen).toEqual([false]);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not pass the prop through to the primitive (and so the DOM)", () => {
    const props = render(<DialogContent preventOutsideClose>Form</DialogContent>);
    expect(props).not.toHaveProperty("preventOutsideClose");
  });
});
