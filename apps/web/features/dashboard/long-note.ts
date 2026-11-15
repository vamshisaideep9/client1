// Staff working notes (call logs, field tasks, task notes). The API caps the
// request at STAFF_NOTE_MAX_CHARS (apps/api/app/schemas/telecaller.py); the
// word limit is what people see.
export const STAFF_NOTE_MAX_WORDS = 1500;
export const STAFF_NOTE_MAX_CHARS = 10_000;

export function countWords(value: string): number {
  const trimmed = value.trim();
  return trimmed ? trimmed.split(/\s+/u).length : 0;
}

/** Returns an error message when a note is over either limit. */
export function staffNoteLimitError(value: string, label = "Notes"): string | undefined {
  if (countWords(value) > STAFF_NOTE_MAX_WORDS) {
    return `${label} must be ${STAFF_NOTE_MAX_WORDS.toLocaleString("en-IN")} words or fewer.`;
  }
  if (value.length > STAFF_NOTE_MAX_CHARS) {
    return `${label} must be ${STAFF_NOTE_MAX_CHARS.toLocaleString("en-IN")} characters or fewer.`;
  }
  return undefined;
}
