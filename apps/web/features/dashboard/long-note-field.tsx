"use client";

import * as React from "react";

import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { STAFF_NOTE_MAX_CHARS, STAFF_NOTE_MAX_WORDS, countWords } from "./long-note";

type LongNoteFieldProps = Omit<React.ComponentProps<typeof Textarea>, "maxLength"> & {
  value: string;
  counterId: string;
};

/**
 * Textarea that grows with its content (up to a scrollable cap) and shows a
 * live word count. The counter is announced politely only near the limit so
 * screen readers are not interrupted on every keystroke.
 */
export function LongNoteField({
  value,
  counterId,
  className,
  "aria-describedby": describedBy,
  ...props
}: LongNoteFieldProps) {
  const words = countWords(value);
  const nearLimit = words >= STAFF_NOTE_MAX_WORDS * 0.9;
  const over = words > STAFF_NOTE_MAX_WORDS || value.length > STAFF_NOTE_MAX_CHARS;

  return (
    <div>
      <Textarea
        {...props}
        value={value}
        maxLength={STAFF_NOTE_MAX_CHARS}
        aria-describedby={[describedBy, counterId].filter(Boolean).join(" ") || undefined}
        className={cn("field-sizing-content max-h-[24rem] min-h-24 resize-y", className)}
      />
      <p
        id={counterId}
        aria-live={nearLimit ? "polite" : "off"}
        className={cn(
          "mt-1 text-right text-xs tabular-nums",
          over ? "font-medium text-destructive" : "text-text-secondary",
        )}
      >
        {words.toLocaleString("en-IN")} / {STAFF_NOTE_MAX_WORDS.toLocaleString("en-IN")} words
      </p>
    </div>
  );
}
