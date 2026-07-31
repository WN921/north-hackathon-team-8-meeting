import "./globals.css";

export const metadata = {
  title: "会务系统",
  description: "北坡内部黑客马拉松第八组会务系统",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
