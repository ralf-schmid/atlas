import Link from "next/link";

// Mobile-first bottom navigation (CLAUDE.md: ~390 px first, touch targets >= 44 px).
// Short labels on purpose: five items on a 390 px screen leave ~62 px of text
// width each — "Leaderboard" would wrap or push the bar into horizontal scroll.
const ITEMS = [
  { href: "/", label: "Übersicht" },
  { href: "/leaderboard", label: "Ranking" },
  { href: "/journal", label: "Journal" },
  { href: "/impulse", label: "Impulse" },
  { href: "/trace", label: "Trace" },
];

export default function BottomNav() {
  return (
    <nav
      aria-label="Hauptnavigation"
      className="fixed inset-x-0 bottom-0 z-10 border-t border-gray-200 bg-white/95 backdrop-blur"
    >
      <ul className="mx-auto flex w-full max-w-md">
        {ITEMS.map((item) => (
          <li key={item.href} className="flex-1">
            <Link
              href={item.href}
              className="flex min-h-[56px] items-center justify-center px-2 text-center text-[13px] font-medium text-gray-700"
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
