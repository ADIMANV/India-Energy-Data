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
const backend = process.env.BACKEND_ORIGIN;

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    if (!backend) return [];
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
