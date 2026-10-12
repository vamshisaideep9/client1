import type { ImageProps } from "next/image";
import type { ImgHTMLAttributes } from "react";

declare global { interface Window { __DRAFT_ASSETS__: Record<string, string>; } }
export function assetUrl(src: string) {
  if (src.startsWith("data:") || src.startsWith("blob:")) return src;
  const asset = window.__DRAFT_ASSETS__[src];
  if (!asset) throw new Error(`Missing embedded draft asset: ${src}`);
  return asset;
}
export function getImageProps({ src, fill, priority, unoptimized: _unoptimized, loader: _loader, placeholder: _placeholder, blurDataURL: _blur, quality: _quality, onLoadingComplete: _onLoadingComplete, ...props }: ImageProps) {
  const path = typeof src === "string" ? src : "default" in src ? src.default.src : src.src;
  const result: ImgHTMLAttributes<HTMLImageElement> = {
    ...props, width: fill ? undefined : props.width, height: fill ? undefined : props.height,
    src: assetUrl(path), loading: priority ? "eager" : (props.loading ?? "lazy"),
    style: fill ? { position: "absolute", inset: 0, width: "100%", height: "100%", ...props.style } : props.style,
  };
  return { props: result };
}
export default function Image(props: ImageProps) {
  // eslint-disable-next-line @next/next/no-img-element -- the draft embeds data URLs
  return <img {...getImageProps(props).props} alt={props.alt} />;
}
