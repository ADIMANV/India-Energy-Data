/** @type {import('next').NextConfig} */

// On Vercel the site is served over HTTPS, so the browser refuses to fetch a
// plain-http API (mixed content) — and Let's Encrypt won't issue a cert for a
// bare IP, so the backend can't be https without a domain. Instead we proxy:
// the browser calls same-origin /api/*, and Vercel forwards it server-side to
// BACKEND_ORIGIN. No certs, no domain, no CORS.
//
// Vercel env vars to set:
//   BACKEND_ORIGIN      = http://<ec2-ip>:8000
//   NEXT_PUBLIC_API_URL = /api
// Locally both stay unset: lib/api.js falls back to http://localhost:8000.
// Trimmed because pasting into a dashboard env-var field routinely picks up a
// leading tab/newline, and Next.js then rejects the rewrite with a confusing
// "does not start with /, http://, or https://" (the value did — after a \t).
const backend = process.env.BACKEND_ORIGIN?.trim();

if (backend && !/^https?:\/\//.test(backend)) {
  throw new Error(
    `BACKEND_ORIGIN must start with http:// or https:// — got ${JSON.stringify(backend)}`,
  );
}

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    if (!backend) return [];
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
