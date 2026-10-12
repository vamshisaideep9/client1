import { ResponsiveArtwork } from "@/components/responsive-artwork";
import { cn } from "@/lib/utils";
import type { CalculatorGroup } from "@/lib/calculators/types";
import { assetUrl } from "./image";

// The live Server Component reads SVG dimensions from disk. The offline
// counterpart reads the same reviewed SVG already embedded in the document.
export function CalculatorHeroArt({ src, className }: { group: CalculatorGroup; src?: string; className?: string }) {
  if (!src) return null;
  const svg = atob(assetUrl(src).split(",")[1]);
  const viewBox = svg.match(/viewBox="[\d.-]+\s+[\d.-]+\s+([\d.]+)\s+([\d.]+)"/);
  const width = viewBox ? Number(viewBox[1]) : 500;
  const height = viewBox ? Number(viewBox[2]) : 500;
  return <div aria-hidden className={cn("hidden shrink-0 items-center justify-center lg:flex lg:w-[460px] [&>picture]:w-full", className)}>
    <ResponsiveArtwork src={src} media="(min-width: 1024px)" width={width} height={height} sizes="460px" className="h-auto w-full max-w-[460px]" loading="eager" fetchPriority="high" />
  </div>;
}
