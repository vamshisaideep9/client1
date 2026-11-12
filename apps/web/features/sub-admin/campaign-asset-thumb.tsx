import * as React from "react";

import type { CampaignMediaAsset } from "@/lib/campaign-media-api";
import { cn } from "@/lib/utils";

/**
 * Media Library thumbnail for one asset. Images render as before; a processed
 * banner video renders its first frame (muted, no autoplay, no download of the
 * full file beyond metadata) so a Sub Admin can recognise it in the grid.
 */
export function CampaignAssetThumb({
  asset,
  width,
  height,
  fit = "cover",
  lazy = true,
}: {
  asset: Pick<CampaignMediaAsset, "image_url" | "alt_text" | "mime_type">;
  width: number;
  height: number;
  fit?: "cover" | "contain";
  lazy?: boolean;
}) {
  const className = cn(
    "absolute inset-0 h-full w-full",
    fit === "cover" ? "object-cover" : "object-contain",
  );
  if (asset.mime_type === "video/mp4") {
    return (
      <video
        src={`${asset.image_url}#t=0.1`}
        muted
        playsInline
        preload="metadata"
        aria-label={asset.alt_text}
        width={width}
        height={height}
        className={className}
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- asset host thumbnails stay direct
    <img
      src={asset.image_url}
      alt={asset.alt_text}
      width={width}
      height={height}
      loading={lazy ? "lazy" : undefined}
      decoding="async"
      className={className}
    />
  );
}
