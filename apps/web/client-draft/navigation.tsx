import { useMemo, useSyncExternalStore } from "react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { toast } from "sonner";
import { unstable_createAdapterProvider, type unstable_UpdateUrlFunction } from "nuqs/adapters/custom";

const changeEvent = "draft:navigate";
function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  window.addEventListener("popstate", listener);
  window.addEventListener(changeEvent, listener);
  return () => { window.removeEventListener("hashchange", listener); window.removeEventListener("popstate", listener); window.removeEventListener(changeEvent, listener); };
}
export function locationSnapshot() { return window.location.hash.startsWith("#/") ? window.location.hash.slice(1) : "/"; }
export function useLocation() { return useSyncExternalStore(subscribe, locationSnapshot, () => "/"); }
export function routeUrl(href = locationSnapshot()) { return new URL(href, "https://draft.invalid"); }
export function usePathname() { return routeUrl(useLocation()).pathname; }
export function useSearchParams() { const location = useLocation(); return useMemo(() => routeUrl(location).searchParams, [location]); }

export function navigate(href: string, replace = false) {
  const url = new URL(href, routeUrl());
  if (url.origin !== "https://draft.invalid") {
    toast.info("External links are disabled in this offline review draft.");
    return;
  }
  if (/^\/(login|register|forgot-password|dashboard|invite)(\/|$)/.test(url.pathname)) {
    toast.info("The client draft includes the public website only.", { description: "Accounts and applications will be available on the live site. Nothing is submitted here." });
    return;
  }
  const destination = `#${url.pathname}${url.search}${url.hash}`;
  if (replace) window.history.replaceState(null, "", destination);
  else if (window.location.hash !== destination) window.history.pushState(null, "", destination);
  window.dispatchEvent(new Event(changeEvent));
}
const router = { push: (href: string) => navigate(href), replace: (href: string) => navigate(href, true), back: () => window.history.back(), forward: () => window.history.forward(), refresh: () => window.dispatchEvent(new Event(changeEvent)), prefetch: async () => {} };
export function useRouter() { return router; }
export function notFound(): never { throw new Error("This page is not included in the public client draft."); }
export function permanentRedirect(href: string): never { navigate(href, true); throw new Error("Redirecting…"); }
export const redirect = permanentRedirect;

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string | { pathname?: string; query?: Record<string, string>; hash?: string };
  prefetch?: boolean | null; replace?: boolean; scroll?: boolean; children?: ReactNode;
};
export default function Link({ href, prefetch: _prefetch, replace: _replace, scroll: _scroll, ...props }: LinkProps) {
  const value = typeof href === "string" ? href : `${href.pathname ?? "/"}${href.query ? `?${new URLSearchParams(href.query)}` : ""}${href.hash ?? ""}`;
  return <a {...props} href={value.startsWith("/") ? `#${value}` : value} />;
}

const updateUrl: unstable_UpdateUrlFunction = (search, options) => {
  const url = routeUrl(); url.search = search.toString();
  navigate(`${url.pathname}${url.search}${url.hash}`, options.history !== "push");
};
export const NuqsAdapter = unstable_createAdapterProvider(function useDraftAdapter() {
  const searchParams = useSearchParams();
  return { searchParams, updateUrl, getSearchParamsSnapshot: () => routeUrl().searchParams };
});
