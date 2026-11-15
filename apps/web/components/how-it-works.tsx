import { BadgeCheck, Landmark, MessageSquareText, PhoneCall } from "lucide-react";
import { type LucideIcon } from "lucide-react";

// Home "How it works": platform-level 4-step flow that covers both business
// lines (loans + real estate) in one voice. Blue-only like the rest of the
// public site (loans-green / realestate-amber stay reserved for authenticated
// dashboards, per docs/design/ui-principles.md).
//
// lg+: the four numbered nodes sit on a horizontal connector line to read as a
// process. The line is masked behind each circle by a bg-colored ring, so
// it joins node to node instead of running through them. Below lg the steps
// stack into a single centered column and the connector is hidden.
type Step = {
  n: number;
  title: string;
  copy: string;
  icon: LucideIcon;
};

const STEPS: Step[] = [
  {
    n: 1,
    title: "Tell us what you need",
    copy: "The online form takes a couple of minutes.",
    icon: MessageSquareText,
  },
  {
    n: 2,
    title: "We match you with lenders",
    copy: "We match you with banks, housing finance companies or NBFCs that lend to profiles like yours.",
    icon: BadgeCheck,
  },
  {
    n: 3,
    title: "An advisor calls you",
    copy: "During working hours, Monday to Saturday, 10 AM to 6 PM, to check eligibility and documents.",
    icon: PhoneCall,
  },
  {
    n: 4,
    title: "The lender decides and pays",
    copy: "The lender reviews your application and, once it approves, pays the loan into your bank account.",
    icon: Landmark,
  },
];

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-it-works-heading"
      className="w-full scroll-mt-[var(--site-header-h)] border-t border-[var(--nav-border)] bg-[var(--nav-bg)]"
    >
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20 lg:px-8 lg:py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h2
            id="how-it-works-heading"
            className="font-heading text-3xl font-semibold text-foreground sm:text-4xl"
          >
            How it works
          </h2>
          <p className="mt-4 text-lg text-text-secondary">
            From your first question to the money in your account, in four steps.
          </p>
        </div>

        <div className="relative mt-14">
          {/* Connector line: spans between the first and last node centers
              (columns sit at 1/6, 1/2, 5/6 of the row width). lg+ only; the
              per-node surface ring hides it behind each circle. */}
          <div
            aria-hidden
            className="pointer-events-none absolute left-[12.5%] right-[12.5%] top-8 hidden h-px bg-[var(--nav-border)] lg:block"
          />
          <ol className="grid gap-12 lg:grid-cols-4 lg:gap-8">
            {STEPS.map((step) => (
              <li
                key={step.n}
                className="flex flex-col items-center text-center"
              >
                <span className="relative z-10 flex h-16 w-16 items-center justify-center rounded-full bg-[var(--nav-primary)] font-heading text-2xl font-semibold text-white ring-8 ring-[var(--nav-bg)]">
                  {step.n}
                  <span className="absolute -bottom-1 -right-1 flex h-7 w-7 items-center justify-center rounded-full bg-[var(--nav-tint)] text-brand-link ring-1 ring-[var(--nav-border)]">
                    <step.icon className="h-4 w-4" aria-hidden />
                  </span>
                </span>
                <h3 className="mt-6 font-heading text-xl font-semibold text-foreground">
                  {step.title}
                </h3>
                <p className="mt-2 max-w-xs text-base text-text-secondary">
                  {step.copy}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
