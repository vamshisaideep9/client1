"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

function block(event: React.SyntheticEvent) {
  event.preventDefault();
}

// Deters casual copying of legal text (Terms, Privacy): text cannot be
// selected, and copy, cut, drag and the context menu are cancelled inside the
// wrapper. This is a deterrent, not protection: the text is still in the page
// source and can be photographed or printed. Links and keyboard focus keep
// working, so accessibility and navigation are unaffected.
export function CopyProtected({
  className,
  children,
  ...props
}: React.ComponentProps<"section">) {
  return (
    <section
      {...props}
      data-copy-protected=""
      onCopy={block}
      onCut={block}
      onDragStart={block}
      onContextMenu={block}
      className={cn("select-none [-webkit-touch-callout:none]", className)}
    >
      {children}
    </section>
  );
}
