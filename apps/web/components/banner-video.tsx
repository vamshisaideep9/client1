"use client";

import * as React from "react";
import { Pause, Play } from "lucide-react";

import { cn } from "@/lib/utils";
import { YOUTUBE_EMBED_ORIGIN, YOUTUBE_THUMBNAIL_ORIGIN } from "@/lib/security-headers";

const YOUTUBE_ID_RE = /^[A-Za-z0-9_-]{11}$/;

function prefersReducedData(): boolean {
  if (typeof navigator === "undefined") return false;
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  return Boolean(connection?.saveData);
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Banner video for public campaigns.
 *
 * - YouTube: a click-to-play facade. Nothing is requested from YouTube until
 *   the visitor presses play (no third-party cookies or scripts on page load);
 *   the iframe then loads from the privacy-enhanced youtube-nocookie.com host,
 *   muted, inside a sandbox. Only the 11-character id is ever interpolated.
 * - Uploaded MP4: a muted, looping, inline video with a visible pause control
 *   (WCAG 2.2.2). It does not autoplay for reduced motion or Save-Data, and it
 *   pauses whenever its carousel slide is not the active one.
 */
export function BannerVideo({
  youtubeId,
  videoUrl,
  poster,
  title,
  active = true,
  onPlayingChange,
  className,
}: {
  youtubeId?: string;
  videoUrl?: string;
  poster?: string;
  title: string;
  active?: boolean;
  onPlayingChange?: (playing: boolean) => void;
  className?: string;
}) {
  const [youtubeStarted, setYoutubeStarted] = React.useState(false);
  const [playing, setPlaying] = React.useState(false);
  const [autoplayAllowed, setAutoplayAllowed] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement>(null);

  React.useEffect(() => {
    setAutoplayAllowed(!prefersReducedMotion() && !prefersReducedData());
  }, []);

  // Keep only the visible slide playing; report state so the carousel can
  // hold its own autoplay while a video is running.
  React.useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (active && autoplayAllowed) {
      void video.play().catch(() => setPlaying(false));
    } else {
      video.pause();
    }
  }, [active, autoplayAllowed]);

  React.useEffect(() => {
    onPlayingChange?.(playing || (youtubeStarted && active));
  }, [playing, youtubeStarted, active, onPlayingChange]);

  React.useEffect(() => {
    if (!active) setYoutubeStarted(false);
  }, [active]);

  if (youtubeId && YOUTUBE_ID_RE.test(youtubeId)) {
    const thumbnail = `${YOUTUBE_THUMBNAIL_ORIGIN}/vi/${youtubeId}/hqdefault.jpg`;
    return (
      <div className={cn("relative overflow-hidden bg-black", className)} data-banner-video="youtube">
        {youtubeStarted ? (
          <iframe
            src={`${YOUTUBE_EMBED_ORIGIN}/embed/${youtubeId}?autoplay=1&mute=1&playsinline=1&rel=0`}
            title={title}
            className="absolute inset-0 h-full w-full border-0"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
            sandbox="allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"
            loading="lazy"
          />
        ) : (
          <button
            type="button"
            onClick={() => setYoutubeStarted(true)}
            aria-label={`Play video: ${title}`}
            className="group absolute inset-0 flex cursor-pointer items-center justify-center focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-ring"
          >
            {/* Remote thumbnail on an exact CSP-allowed host; next/image would proxy it. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={poster ?? thumbnail}
              alt=""
              className="absolute inset-0 h-full w-full object-cover"
              loading="lazy"
              decoding="async"
            />
            <span className="relative flex h-16 w-16 items-center justify-center rounded-full bg-white/90 text-brand-navy shadow-lg backdrop-blur-sm transition-transform group-hover:scale-105 motion-reduce:transition-none">
              <Play className="ml-1 h-7 w-7" aria-hidden />
            </span>
          </button>
        )}
      </div>
    );
  }

  if (!videoUrl) return null;

  return (
    <div className={cn("relative overflow-hidden bg-black", className)} data-banner-video="upload">
      <video
        ref={videoRef}
        src={videoUrl}
        poster={poster}
        muted
        loop
        playsInline
        preload="metadata"
        aria-label={title}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        className="absolute inset-0 h-full w-full object-cover"
      />
      <button
        type="button"
        onClick={() => {
          const video = videoRef.current;
          if (!video) return;
          if (video.paused) void video.play().catch(() => setPlaying(false));
          else video.pause();
        }}
        aria-label={playing ? `Pause video: ${title}` : `Play video: ${title}`}
        className="absolute bottom-3 right-3 z-10 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full bg-white/85 text-brand-navy shadow backdrop-blur-sm hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {playing ? <Pause className="h-5 w-5" aria-hidden /> : <Play className="ml-0.5 h-5 w-5" aria-hidden />}
      </button>
    </div>
  );
}
