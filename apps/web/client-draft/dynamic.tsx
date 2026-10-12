import { lazy, Suspense, type ComponentType } from "react";
export default function dynamic<P extends object>(load: () => Promise<ComponentType<P>>) {
  const Component = lazy(async () => ({ default: await load() }));
  return function DraftDynamic(props: P) {
    return <Suspense fallback={<p role="status">Loading calculator…</p>}><Component {...props} /></Suspense>;
  };
}
