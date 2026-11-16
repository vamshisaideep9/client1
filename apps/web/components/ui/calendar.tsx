"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DayPicker } from "react-day-picker";

import { cn } from "@/lib/utils";

// Styled react-day-picker (v10). No library stylesheet is imported; every part
// is styled through classNames with the design tokens, and the selection state
// is always conveyed by more than colour (filled pill for the ends, tinted band
// for the middle, plus aria-selected from the library).
export function Calendar({ className, classNames, components, ...props }: React.ComponentProps<typeof DayPicker>) {
  return (
    <DayPicker
      weekStartsOn={1}
      className={cn("p-3", className)}
      classNames={{
        root: "relative",
        months: "flex flex-col gap-4 sm:flex-row sm:gap-6",
        month: "space-y-3",
        month_caption: "flex h-9 items-center justify-center",
        caption_label: "text-sm font-semibold text-text-primary",
        nav: "absolute inset-x-3 top-3 flex h-9 items-center justify-between",
        button_previous:
          "inline-flex h-9 w-9 items-center justify-center rounded-md text-text-secondary hover:bg-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40",
        button_next:
          "inline-flex h-9 w-9 items-center justify-center rounded-md text-text-secondary hover:bg-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40",
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday: "w-10 text-center text-xs font-medium text-text-secondary",
        week: "mt-1 flex w-full",
        day: "group/day relative h-10 w-10 p-0 text-center text-sm",
        day_button:
          "inline-flex h-10 w-10 items-center justify-center rounded-md font-normal text-text-primary transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
        selected: "[&>button]:font-semibold",
        range_start: "rounded-l-md bg-brand-cta-tint [&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary",
        range_end: "rounded-r-md bg-brand-cta-tint [&>button]:bg-primary [&>button]:text-primary-foreground [&>button]:hover:bg-primary",
        range_middle: "bg-brand-cta-tint [&>button]:rounded-none [&>button]:text-brand-link",
        today: "[&>button]:underline [&>button]:decoration-2 [&>button]:underline-offset-4",
        outside: "[&>button]:text-text-secondary/60",
        disabled: "[&>button]:cursor-not-allowed [&>button]:text-text-secondary/40 [&>button]:hover:bg-transparent",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation }) =>
          orientation === "left" ? (
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          ),
        ...components,
      }}
      {...props}
    />
  );
}
