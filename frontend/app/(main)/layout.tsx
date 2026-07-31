"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, readStoredAuth, type StoredAuth } from "@/lib/api";

const navItems = [
  { href: "/", label: "首页" },
  { href: "/rooms", label: "会议室" },
  { href: "/calendar", label: "日历" },
  { href: "/nl/query", label: "自然语言" },
  { href: "/rules", label: "规则配置" },
  { href: "/bookings", label: "预约" },
  { href: "/floor-plan", label: "平面图" },
];

export default function MainLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [auth, setAuth] = useState<StoredAuth | null>(null);

  useEffect(() => {
    const stored = readStoredAuth();
    if (!stored) {
      window.location.assign("/login");
      return;
    }
    setAuth(stored);
    api.me(stored.token).catch(() => {
      window.location.assign("/login");
    });
  }, []);

  if (!auth) {
    return null;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" href="/">会务系统</Link>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.href} className={`nav-link ${pathname === item.href ? "active" : ""}`} href={item.href}>{item.label}</Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span>当前用户：{auth.user.name}</span>
          <span className="muted">本地演示 / RFC-0003</span>
        </div>
      </aside>
      <div className="content">{children}</div>
    </div>
  );
}
