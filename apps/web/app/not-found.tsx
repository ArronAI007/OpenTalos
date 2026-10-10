import Link from "next/link";

export default function NotFound() {
  return (
    <section className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-lg font-semibold">页面不存在</p>
      <Link href="/" className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white">
        回到首页
      </Link>
    </section>
  );
}
