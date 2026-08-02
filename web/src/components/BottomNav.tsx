import Link from "next/link";

// Mobile-first bottom navigation (CLAUDE.md: ~390 px first, touch targets >= 44 px).
const ITEMS = [
  { href: "/", label: "Übersicht" },
  { href: "/leaderboard", label: "Leaderboard" },
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
              className="flex min-h-[56px] items-center justify-center px-3 text-sm font-medium text-gray-700"
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
