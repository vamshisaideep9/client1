"use client";

import * as React from "react";
import { Download, Eye, FileWarning, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { MAX_INLINE_DOCUMENT_BYTES, sniffDocument, type DocumentKind } from "@/lib/document-sniff";
import { cn } from "@/lib/utils";

/** Pages drawn up front; long PDFs reveal the rest on request. */
const INITIAL_PAGES = 10;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "image"; objectUrl: string; kind: DocumentKind }
  | { status: "pdf"; data: Uint8Array };

/**
 * Shows an authorised document inside the dashboard.
 *
 * The bytes come from the caller's existing short-lived signed URL (the API
 * already decided this viewer may read them). The format is decided from the
 * bytes, not the URL. Images are drawn from a typed blob URL; PDFs are drawn
 * page by page onto canvases by PDF.js, with no annotation/link layer, no XFA
 * forms and no document scripting, so content embedded in an uploaded PDF never
 * runs. Anything else is offered as a download only.
 */
export function DocumentViewer({
  url,
  label,
  className,
}: {
  url: string;
  label: string;
  className?: string;
}) {
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  React.useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setState({ status: "loading" });

    void (async () => {
      try {
        const response = await fetch(url, {
          credentials: "omit",
          cache: "no-store",
          referrerPolicy: "no-referrer",
        });
        if (!response.ok) throw new Error("unavailable");
        const declared = Number(response.headers.get("content-length") ?? "0");
        if (declared > MAX_INLINE_DOCUMENT_BYTES) throw new Error("too-large");
        const buffer = new Uint8Array(await response.arrayBuffer());
        if (buffer.byteLength > MAX_INLINE_DOCUMENT_BYTES) throw new Error("too-large");
        const kind = sniffDocument(buffer);
        if (cancelled) return;
        if (kind === "pdf") {
          setState({ status: "pdf", data: buffer });
        } else if (kind !== "unsupported") {
          objectUrl = URL.createObjectURL(new Blob([buffer], { type: kind }));
          setState({ status: "image", objectUrl, kind });
        } else {
          setState({ status: "error", message: "This file type can't be shown here." });
        }
      } catch (error) {
        if (cancelled) return;
        setState({
          status: "error",
          message:
            error instanceof Error && error.message === "too-large"
              ? "This file is too large to show here."
              : "The document couldn't be loaded. The link may have expired; close and reopen it.",
        });
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  return (
    <div className={cn("min-h-48", className)}>
      {state.status === "loading" ? (
        <div
          role="status"
          className="flex h-48 items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 text-sm text-text-secondary"
        >
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading document…
        </div>
      ) : state.status === "error" ? (
        <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 p-6 text-center">
          <FileWarning className="h-6 w-6 text-text-secondary" aria-hidden="true" />
          <p className="text-sm text-text-secondary">{state.message}</p>
          <Button asChild size="sm" variant="outline">
            <a href={url} target="_blank" rel="noreferrer">
              <Download className="h-4 w-4" aria-hidden="true" />
              Download instead
            </a>
          </Button>
        </div>
      ) : state.status === "image" ? (
        // Short-lived blob URL of re-encoded upload bytes; next/image cannot
        // optimise blob: sources, so this stays a plain <img>.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={state.objectUrl}
          alt={label}
          className="mx-auto max-h-[70vh] w-auto max-w-full rounded-lg border border-border bg-muted/30 object-contain"
        />
      ) : (
        <PdfPages data={state.data} label={label} />
      )}
    </div>
  );
}

function PdfPages({ data, label }: { data: Uint8Array; label: string }) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [pageCount, setPageCount] = React.useState(0);
  const [limit, setLimit] = React.useState(INITIAL_PAGES);
  const [error, setError] = React.useState(false);
  const [rendering, setRendering] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;
    let destroy: (() => Promise<void>) | null = null;

    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        if (!pdfjs.GlobalWorkerOptions.workerSrc) {
          pdfjs.GlobalWorkerOptions.workerSrc = new URL(
            "pdfjs-dist/build/pdf.worker.min.mjs",
            import.meta.url,
          ).toString();
        }
        // A copy: PDF.js transfers the buffer to its worker.
        const task = pdfjs.getDocument({
          data: data.slice(),
          enableXfa: false,
          useWorkerFetch: false,
          disableAutoFetch: true,
          stopAtErrors: false,
        });
        destroy = () => task.destroy();
        const document = await task.promise;
        if (cancelled) return;
        setPageCount(document.numPages);
        container.replaceChildren();
        const width = Math.max(container.clientWidth, 320);
        const ratio = window.devicePixelRatio || 1;
        for (let number = 1; number <= Math.min(document.numPages, limit); number += 1) {
          const page = await document.getPage(number);
          if (cancelled) return;
          const base = page.getViewport({ scale: 1 });
          const viewport = page.getViewport({ scale: (width / base.width) * ratio });
          const canvas = window.document.createElement("canvas");
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          canvas.style.width = "100%";
          canvas.setAttribute("role", "img");
          canvas.setAttribute("aria-label", `${label}, page ${number} of ${document.numPages}`);
          canvas.className = "rounded-md border border-border bg-white";
          container.appendChild(canvas);
          await page.render({
            canvas,
            viewport,
            annotationMode: pdfjs.AnnotationMode.ENABLE,
          }).promise;
        }
        if (!cancelled) setRendering(false);
      } catch {
        if (!cancelled) {
          setError(true);
          setRendering(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      void destroy?.();
    };
  }, [data, label, limit]);

  if (error) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-muted/30 p-6 text-center text-sm text-text-secondary">
        This PDF couldn&rsquo;t be displayed. Use Download to open it.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {rendering ? (
        <p role="status" className="flex items-center gap-2 text-sm text-text-secondary">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Rendering pages…
        </p>
      ) : null}
      <div ref={containerRef} className="space-y-3" data-testid="pdf-pages" />
      {!rendering && pageCount > limit ? (
        <Button variant="outline" size="sm" onClick={() => setLimit(pageCount)}>
          Show all {pageCount} pages
        </Button>
      ) : null}
    </div>
  );
}

/** A "View" button that opens the document in the in-dashboard viewer. */
export function ViewDocumentButton({
  url,
  title,
  children = "View",
  className,
  variant = "outline",
  size = "sm",
}: {
  url: string;
  title: string;
  children?: React.ReactNode;
  className?: string;
  variant?: "outline" | "default" | "ghost";
  size?: "sm" | "default";
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button
        type="button"
        size={size}
        variant={variant}
        className={className}
        onClick={() => setOpen(true)}
        aria-label={typeof children === "string" ? `${children}: ${title}` : undefined}
      >
        <Eye className="h-4 w-4" aria-hidden="true" />
        {children}
      </Button>
      <DocumentViewerDialog url={open ? url : null} title={title} onClose={() => setOpen(false)} />
    </>
  );
}

/** The viewer in a dialog, with a download fallback. `url` null closes it. */
export function DocumentViewerDialog({
  url,
  title,
  description,
  onClose,
}: {
  url: string | null;
  title: string;
  description?: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={url !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description ?? "Shown inside the dashboard. Nothing in the file can run here."}
          </DialogDescription>
        </DialogHeader>
        {url ? (
          <>
            <DocumentViewer url={url} label={title} />
            <div className="flex justify-end">
              <Button asChild size="sm" variant="ghost">
                <a href={url} target="_blank" rel="noreferrer">
                  <Download className="h-4 w-4" aria-hidden="true" />
                  Download
                </a>
              </Button>
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
